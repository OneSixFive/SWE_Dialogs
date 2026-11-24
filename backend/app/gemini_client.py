from __future__ import annotations

import base64
import json
import struct
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException, status

from .config import Settings


DEFAULT_MODEL = "gemini-2.5-pro-preview-tts"


async def generate_wav(settings: Settings, *, dialog: str, model: str | None = None) -> bytes:
    selected_model = model or DEFAULT_MODEL
    encoded_key = quote(settings.gemini_api_key, safe="")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{selected_model}:generateContent?key={encoded_key}"
    )
    body = {
        "contents": [{"parts": [{"text": dialog}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "multiSpeakerVoiceConfig": {
                    "speakerVoiceConfigs": [
                        {
                            "speaker": "Anna",
                            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Aoede"}},
                        },
                        {
                            "speaker": "Erik",
                            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Enceladus"}},
                        },
                    ]
                }
            },
        },
    }
    async with httpx.AsyncClient(timeout=settings.gemini_timeout_seconds) as client:
        response = await client.post(url, json=body)

    if response.status_code < 200 or response.status_code > 299:
        public_status = status.HTTP_429_TOO_MANY_REQUESTS if response.status_code == 429 else status.HTTP_502_BAD_GATEWAY
        public_detail = "Gemini rate limited the audio request." if response.status_code == 429 else "Gemini audio generation failed."
        raise HTTPException(
            status_code=public_status,
            detail=public_detail,
        )

    decoded = response.json()
    pcm_data = _extract_pcm_data(decoded)
    return build_wav_from_pcm(pcm_data)


def _extract_pcm_data(decoded: dict[str, Any]) -> bytes:
    try:
        b64 = decoded["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        return base64.b64decode(b64)
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gemini returned no audio.",
        ) from error


def build_wav_from_pcm(pcm_data: bytes) -> bytes:
    sample_rate = 24_000
    channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * channels * (bits_per_sample // 8)
    block_align = channels * (bits_per_sample // 8)
    data_size = len(pcm_data)
    riff_chunk_size = 36 + data_size

    header = b"".join(
        [
            b"RIFF",
            struct.pack("<I", riff_chunk_size),
            b"WAVE",
            b"fmt ",
            struct.pack("<I", 16),
            struct.pack("<H", 1),
            struct.pack("<H", channels),
            struct.pack("<I", sample_rate),
            struct.pack("<I", byte_rate),
            struct.pack("<H", block_align),
            struct.pack("<H", bits_per_sample),
            b"data",
            struct.pack("<I", data_size),
        ]
    )
    return header + pcm_data


GEMINI_THINKING_LEVELS = {"minimal", "low", "medium", "high"}


async def send_structured_gemini_request(
    settings: Settings,
    *,
    user_id: int | None,
    request_role: str,
    request_name: str,
    prompt_version: str,
    source_id: str | None,
    model: str,
    reasoning_effort: str,
    instructions: str,
    user_text: str,
    schema: dict[str, Any],
    max_output_tokens: int,
    usage_recorder: Any = None,
) -> dict[str, Any]:
    """Structured JSON call through Gemini generateContent (used for gemini-* text models)."""
    from .openai_client import _estimated_cost_metrics, logger, short_sha256

    effort = reasoning_effort.strip().lower()
    thinking_level = effort if effort in GEMINI_THINKING_LEVELS else "high"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='')}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": instructions}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": schema["schema"],
            "maxOutputTokens": max_output_tokens,
            "thinkingConfig": {"thinkingLevel": thinking_level},
        },
    }
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=settings.gemini_timeout_seconds) as client:
        response = await client.post(url, json=body, headers={"x-goog-api-key": settings.gemini_api_key})
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code < 200 or response.status_code > 299:
        reason = ""
        try:
            reason = str(response.json().get("error", {}).get("message", ""))[:300]
        except ValueError:
            pass
        logger.warning(
            "gemini_request_failed %s",
            json.dumps({"request": request_name, "model": model, "status": response.status_code, "reason": reason}),
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS if response.status_code == 429 else status.HTTP_502_BAD_GATEWAY,
            detail="Gemini rate limited the request." if response.status_code == 429 else "Gemini request failed.",
        )

    decoded = response.json()
    usage = decoded.get("usageMetadata") or {}
    prompt_tokens = int(usage.get("promptTokenCount") or 0)
    cached_tokens = int(usage.get("cachedContentTokenCount") or 0)
    thoughts_tokens = int(usage.get("thoughtsTokenCount") or 0)
    # Thinking is billed as output, so it is counted in output_tokens like OpenAI reasoning tokens.
    output_tokens = int(usage.get("candidatesTokenCount") or 0) + thoughts_tokens
    cost_metrics = _estimated_cost_metrics(
        settings,
        model,
        {
            "input_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "input_tokens_details": {"cached_tokens": cached_tokens},
        },
    )
    candidate = (decoded.get("candidates") or [{}])[0]
    request_id = response.headers.get("x-goog-request-id") or decoded.get("responseId")
    logger.info(
        "gemini_response_usage %s",
        json.dumps(
            {
                "request": request_name,
                "model": model,
                "served_model": decoded.get("modelVersion"),
                "lesson_id": source_id,
                "finish_reason": candidate.get("finishReason"),
                "thinking_level": thinking_level,
                "elapsed_ms": elapsed_ms,
                "gemini_response_id": request_id,
                "instructions_sha256": short_sha256(instructions),
                "input_tokens": prompt_tokens,
                "cached_tokens": cached_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": thoughts_tokens,
                **cost_metrics,
            },
            sort_keys=True,
        ),
    )
    if usage_recorder is not None and user_id is not None:
        usage_recorder(
            {
                "user_id": user_id,
                "request_role": request_role,
                "request_name": request_name,
                "source_id": source_id,
                "model": model,
                "prompt_version": prompt_version,
                "prompt_cache_key": None,
                "input_tokens": prompt_tokens,
                "cached_tokens": cached_tokens,
                "cache_write_tokens": 0,
                "ordinary_input_tokens": max(prompt_tokens - cached_tokens, 0),
                "output_tokens": output_tokens,
                "reasoning_tokens": thoughts_tokens,
                "total_tokens": prompt_tokens + output_tokens,
                **cost_metrics,
                "actual_cost_usd": None,
                "elapsed_ms": elapsed_ms,
                "openai_request_id": request_id,
                "created_at": datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
                "raw_usage": usage,
            }
        )

    text = "".join(
        part.get("text", "")
        for part in (candidate.get("content") or {}).get("parts", [])
        if not part.get("thought")
    )
    try:
        result = json.loads(text)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Gemini returned invalid structured JSON.") from error
    if not isinstance(result, dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Gemini returned unexpected JSON.")
    return result
