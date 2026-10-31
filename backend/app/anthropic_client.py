from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Awaitable

import anthropic
from fastapi import HTTPException, status

from .config import Settings
from .openai_client import (
    UsageRecorder,
    _estimated_cost_metrics,
    json_string,
    logger,
    short_sha256,
    speaker_schema,
)


ANTHROPIC_FALLBACK_BETA = "server-side-fallback-2026-07-01"
ANTHROPIC_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
REPLAYED_BLOCK_TYPES = {"thinking", "redacted_thinking", "text"}
OPENING_STAGE_DIRECTION = "(Övningen börjar. Eleven har inte sagt något ännu.)"


@lru_cache(maxsize=4)
def _client(api_key: str, timeout_seconds: float) -> anthropic.AsyncAnthropic:
    # One long-lived client per key keeps the HTTPS connection warm between Speaking turns.
    return anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_seconds, max_retries=1)


def _effort(reasoning_effort: str) -> str:
    effort = reasoning_effort.strip().lower()
    return effort if effort in ANTHROPIC_EFFORTS else "low"


def _replay_block(block: Any) -> dict[str, Any]:
    if block.type == "thinking":
        return {"type": "thinking", "thinking": block.thinking, "signature": block.signature}
    if block.type == "redacted_thinking":
        return {"type": "redacted_thinking", "data": block.data}
    return {"type": "text", "text": block.text}


async def send_speaker_turn_anthropic(
    settings: Settings,
    *,
    user_id: int,
    lesson_id: str,
    instructions: str,
    prior_provider_messages: list[dict[str, Any]],
    speaker_state: dict[str, Any],
    latest_learner_transcript: str | None,
    usage_recorder: UsageRecorder | None = None,
) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Anthropic is not configured.")
    model = settings.speaker_model

    # Native turns: the learner's words as the user turn, backend state as a system message after it,
    # and earlier tutor turns replayed exactly as returned (thinking included). The history is
    # append-only, so each turn's breakpoint on the latest user turn reads back the previous one.
    user_message = {
        "role": "user",
        "content": [{"type": "text", "text": latest_learner_transcript or OPENING_STAGE_DIRECTION}],
    }
    state_message = {"role": "system", "content": f"speaker_state_json:\n{json_string(speaker_state)}"}
    cached_user_message = {
        "role": "user",
        "content": [{**user_message["content"][0], "cache_control": {"type": "ephemeral"}}],
    }
    messages = [*prior_provider_messages, cached_user_message, state_message]

    schema = speaker_schema()
    started = time.perf_counter()
    response = await _create(
        _client(settings.anthropic_api_key, settings.speaker_provider_timeout_seconds).messages.create(
            model=model,
            max_tokens=4_000,
            system=[{"type": "text", "text": instructions, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            output_config={
                "effort": _effort(settings.speaker_reasoning_effort),
                "format": {"type": "json_schema", "schema": schema["schema"]},
            },
        )
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    usage_event = _log_anthropic_usage(
        settings,
        user_id=user_id,
        request_role="Speaking",
        request_name="speaker_turn",
        prompt_version="speaker_v1",
        source_id=lesson_id,
        model=model,
        instructions=instructions,
        input_messages=len(messages),
        response=response,
        elapsed_ms=elapsed_ms,
    )
    if usage_event is not None and usage_recorder is not None:
        usage_recorder(usage_event)
    decoded = _structured_output(response)
    assistant_message = {
        "role": "assistant",
        "content": [_replay_block(block) for block in response.content if block.type in REPLAYED_BLOCK_TYPES],
    }
    decoded["provider_messages"] = [user_message, state_message, assistant_message]
    return decoded


async def send_structured_anthropic_request(
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
    max_tokens: int,
    timeout_seconds: float,
    usage_recorder: UsageRecorder | None = None,
) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Anthropic is not configured.")
    started = time.perf_counter()
    response = await _create(
        _client(settings.anthropic_api_key, timeout_seconds).beta.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=instructions,
            messages=[{"role": "user", "content": user_text}],
            output_config={
                "effort": _effort(reasoning_effort),
                "format": {"type": "json_schema", "schema": schema["schema"]},
            },
            betas=[ANTHROPIC_FALLBACK_BETA],
            fallbacks="default",
        )
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    usage_event = _log_anthropic_usage(
        settings,
        user_id=user_id,
        request_role=request_role,
        request_name=request_name,
        prompt_version=prompt_version,
        source_id=source_id,
        model=model,
        instructions=instructions,
        input_messages=1,
        response=response,
        elapsed_ms=elapsed_ms,
    )
    if usage_event is not None and usage_recorder is not None:
        usage_recorder(usage_event)
    return _structured_output(response)


async def _create(request: Awaitable[Any]) -> Any:
    try:
        return await request
    except anthropic.APIStatusError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Anthropic error: {error.message}",
        ) from error
    except anthropic.APIConnectionError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Anthropic connection failed.") from error


def _structured_output(response: Any) -> dict[str, Any]:
    if response.stop_reason == "refusal":
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Anthropic refused the request.")
    output_text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not output_text:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Anthropic returned no structured output.")
    try:
        decoded = json.loads(output_text)
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Anthropic returned invalid structured JSON.",
        ) from error
    if not isinstance(decoded, dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Anthropic returned unexpected JSON.")
    return decoded


def _log_anthropic_usage(
    settings: Settings,
    *,
    user_id: int | None,
    request_role: str,
    request_name: str,
    prompt_version: str,
    source_id: str | None,
    model: str,
    instructions: str,
    input_messages: int,
    response: Any,
    elapsed_ms: int,
) -> dict[str, Any] | None:
    raw_usage = response.usage.to_dict()
    uncached = response.usage.input_tokens or 0
    cache_read = response.usage.cache_read_input_tokens or 0
    cache_write = response.usage.cache_creation_input_tokens or 0
    output_tokens = response.usage.output_tokens or 0
    input_tokens = uncached + cache_read + cache_write
    # OpenAI-shaped usage so the shared price table and dashboard math apply unchanged.
    cost_metrics = _estimated_cost_metrics(
        settings,
        model,
        {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "input_tokens_details": {"cached_tokens": cache_read, "cache_write_tokens": cache_write},
        },
    )
    request_id = getattr(response, "_request_id", None)
    logger.info(
        "anthropic_response_usage %s",
        json.dumps(
            {
                "request": request_name,
                "model": model,
                "served_model": response.model,
                "lesson_id": source_id,
                "stop_reason": response.stop_reason,
                "elapsed_ms": elapsed_ms,
                "anthropic_request_id": request_id,
                "instructions_sha256": short_sha256(instructions),
                "input_messages": input_messages,
                "input_tokens": input_tokens,
                "cached_tokens": cache_read,
                "cache_write_tokens": cache_write,
                "ordinary_input_tokens": uncached,
                "output_tokens": output_tokens,
                "cache_read_ratio": round(cache_read / input_tokens, 4) if input_tokens else None,
                **cost_metrics,
            },
            sort_keys=True,
        ),
    )
    if user_id is None:
        return None
    return {
        "user_id": user_id,
        "request_role": request_role,
        "request_name": request_name,
        "source_id": source_id,
        "model": model,
        "prompt_version": prompt_version,
        "prompt_cache_key": None,
        "input_tokens": input_tokens,
        "cached_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "ordinary_input_tokens": uncached,
        "output_tokens": output_tokens,
        "reasoning_tokens": None,
        "total_tokens": input_tokens + output_tokens,
        **cost_metrics,
        "actual_cost_usd": None,
        "elapsed_ms": elapsed_ms,
        "openai_request_id": request_id,
        "created_at": datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "raw_usage": raw_usage,
    }
