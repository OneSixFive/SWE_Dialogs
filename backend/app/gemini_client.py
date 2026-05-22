from __future__ import annotations

import base64
import struct
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException, status

from .config import Settings


DEFAULT_MODEL = "gemini-3.1-flash-tts-preview"


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
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gemini error: {response.text[:500] or response.status_code}",
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
