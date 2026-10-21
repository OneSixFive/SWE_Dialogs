from __future__ import annotations

import logging
import math
import struct
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from .config import Settings


TRANSCRIPTION_URL = "https://api.openai.com/v1/audio/transcriptions"
ELEVENLABS_STREAM_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
SPEAKER_PCM_SAMPLE_RATE = 24_000
SPEAKER_PCM_OUTPUT_FORMAT = "pcm_24000"
MAX_TURN_AUDIO_SECONDS = 65.0
MIN_TURN_AUDIO_SECONDS = 0.3
logger = logging.getLogger("uvicorn.error")


class SpeechProviderError(Exception):
    def __init__(self, provider: str, *, status_code: int | None = None) -> None:
        super().__init__(f"{provider} speech request failed.")
        self.provider = provider
        self.status_code = status_code


@dataclass(frozen=True)
class Transcription:
    text: str
    audio_seconds: float
    elapsed_ms: int
    request_id: str | None
    raw_usage: dict[str, Any]


def wav_duration_seconds(data: bytes) -> float:
    """Validate a mono 16-bit PCM WAV upload and return its duration."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("Audio must be a WAV file.")
    offset = 12
    byte_rate: int | None = None
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        chunk_size = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        body = offset + 8
        if chunk_id == b"fmt ":
            if chunk_size < 16 or body + 16 > len(data):
                raise ValueError("WAV format chunk is invalid.")
            audio_format, channels, sample_rate, rate, _, bits = struct.unpack("<HHIIHH", data[body : body + 16])
            if audio_format != 1 or channels != 1 or bits != 16 or not 8_000 <= sample_rate <= 48_000:
                raise ValueError("Audio must be mono 16-bit PCM.")
            byte_rate = rate
        elif chunk_id == b"data":
            if byte_rate is None or byte_rate <= 0:
                raise ValueError("WAV format chunk must precede audio data.")
            return min(chunk_size, len(data) - body) / byte_rate
        offset = body + chunk_size + (chunk_size % 2)
    raise ValueError("WAV file has no audio data.")


async def transcribe_learner_audio(settings: Settings, *, wav: bytes, context: str) -> Transcription:
    audio_seconds = wav_duration_seconds(wav)
    prompt = f"{context}\nTranskribera ordagrant och behåll elevens grammatiska fel."
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=settings.speaker_provider_timeout_seconds) as client:
        response = await client.post(
            TRANSCRIPTION_URL,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            files={"file": ("turn.wav", wav, "audio/wav")},
            data={
                "model": settings.speaker_transcription_model,
                "language": "sv",
                "prompt": prompt,
                "response_format": "json",
            },
        )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code != 200:
        logger.warning(
            "speaker_transcription_failed status=%s request_id=%s",
            response.status_code,
            response.headers.get("x-request-id"),
        )
        raise SpeechProviderError("OpenAI transcription", status_code=response.status_code)
    payload = response.json()
    text = payload.get("text") if isinstance(payload, dict) else None
    usage = payload.get("usage") if isinstance(payload, dict) else None
    return Transcription(
        text=text.strip() if isinstance(text, str) else "",
        audio_seconds=audio_seconds,
        elapsed_ms=elapsed_ms,
        request_id=response.headers.get("x-request-id"),
        raw_usage=usage if isinstance(usage, dict) else {},
    )


class SpeechStream:
    """An open ElevenLabs PCM stream whose first chunk has already arrived."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        response: httpx.Response,
        chunks: AsyncIterator[bytes],
        first_chunk: bytes,
        first_audio_ms: int,
    ) -> None:
        self._client = client
        self._response = response
        self._chunks = chunks
        self._first_chunk = first_chunk
        self.first_audio_ms = first_audio_ms

    async def pcm_chunks(self) -> AsyncIterator[bytes]:
        """Yield 16-bit aligned PCM so clients never receive half a sample."""
        carry = b""
        pending = [self._first_chunk]
        while True:
            if pending:
                chunk = pending.pop()
            else:
                try:
                    chunk = await anext(self._chunks)
                except StopAsyncIteration:
                    break
            data = carry + chunk
            aligned = len(data) - len(data) % 2
            carry = data[aligned:]
            if aligned:
                yield data[:aligned]

    async def aclose(self) -> None:
        await self._response.aclose()
        await self._client.aclose()


async def open_speech_stream(settings: Settings, *, text: str) -> SpeechStream:
    if not settings.elevenlabs_api_key:
        raise SpeechProviderError("ElevenLabs")
    client = httpx.AsyncClient(timeout=settings.speaker_provider_timeout_seconds)
    try:
        started = time.perf_counter()
        request = client.build_request(
            "POST",
            ELEVENLABS_STREAM_URL.format(voice_id=settings.speaker_tts_voice_id),
            params={"output_format": SPEAKER_PCM_OUTPUT_FORMAT},
            headers={"xi-api-key": settings.elevenlabs_api_key},
            json={"text": text, "model_id": settings.speaker_tts_model, "language_code": "sv"},
        )
        response = await client.send(request, stream=True)
        if response.status_code != 200:
            await response.aread()
            await response.aclose()
            logger.warning(
                "speaker_tts_failed status=%s request_id=%s",
                response.status_code,
                response.headers.get("request-id"),
            )
            raise SpeechProviderError("ElevenLabs", status_code=response.status_code)
        chunks = response.aiter_bytes()
        async for chunk in chunks:
            if chunk:
                first_audio_ms = int((time.perf_counter() - started) * 1000)
                return SpeechStream(client, response, chunks, chunk, first_audio_ms)
        await response.aclose()
        raise SpeechProviderError("ElevenLabs")
    except BaseException:
        await client.aclose()
        raise


def speech_usage_event(
    settings: Settings,
    *,
    user_id: int,
    lesson_id: str,
    request_name: str,
    model: str,
    elapsed_ms: int,
    audio_seconds: float | None = None,
    characters: int | None = None,
    request_id: str | None = None,
    raw_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Usage row for non-token speech calls, priced by `per_minute` or `per_1k_characters` overrides."""
    prices = (settings.openai_usage_price_overrides or {}).get(model)
    prices = prices if isinstance(prices, dict) else {}
    estimated_cost: float | None = None
    if audio_seconds is not None and _price(prices.get("per_minute")) is not None:
        estimated_cost = audio_seconds / 60 * float(prices["per_minute"])
    elif characters is not None and _price(prices.get("per_1k_characters")) is not None:
        estimated_cost = characters / 1000 * float(prices["per_1k_characters"])
    usage = dict(raw_usage or {})
    if audio_seconds is not None:
        usage["audio_seconds"] = round(audio_seconds, 3)
    if characters is not None:
        usage["characters"] = characters
    return {
        "user_id": user_id,
        "request_role": "Speaking",
        "request_name": request_name,
        "source_id": lesson_id,
        "model": model,
        "estimated_cost_usd": round(estimated_cost, 8) if estimated_cost is not None else None,
        "actual_cost_usd": None,
        "elapsed_ms": elapsed_ms,
        "openai_request_id": request_id,
        "created_at": datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "raw_usage": usage,
    }


def _price(value: Any) -> float | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    price = float(value)
    return price if math.isfinite(price) and price >= 0 else None
