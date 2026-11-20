"""Lesson dialog audio: one entry point, provider chosen by the model name.

`eleven_*` models go to ElevenLabs (one request per dialog line, each with its speaker's voice, joined with a
short pause); anything else goes to Gemini multi-speaker TTS. Both return 24 kHz mono s16le WAV.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging

import httpx
from fastapi import HTTPException, status

from .audio_loudness import apply_gain, measure, shared_level_gains
from .config import DIALOG_RANDOM_EXCLUDED_VOICES, DIALOG_RANDOM_VOICE_WEIGHTS, ELEVENLABS_VOICES, Settings
from .gemini_client import DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
from .gemini_client import build_wav_from_pcm
from .gemini_client import generate_wav as generate_gemini_wav


logger = logging.getLogger("uvicorn.error")

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
ELEVENLABS_PCM_OUTPUT_FORMAT = "pcm_24000"
PCM_BYTES_PER_SECOND = 24_000 * 2
LINE_PAUSE_SECONDS = 0.4
# Each voice's lines get one gain toward this loudness (BS.1770), never pushing peaks above the ceiling.
DIALOG_TARGET_LUFS = -19.0
DIALOG_PEAK_CEILING_DBFS = -1.0
# Up to this much of a voice's peaks may be shaved by the lookahead limiter to let it reach the common level.
DIALOG_LIMITER_MAX_DB = 2.0
DIALOG_LIMITER_LOOKAHEAD_SECONDS = 0.005
MAX_PARALLEL_LINE_REQUESTS = 3


def is_elevenlabs_model(model: str | None) -> bool:
    return (model or "").startswith("eleven")


def dialog_tts_provider(model: str | None) -> str:
    return "elevenlabs" if is_elevenlabs_model(model) else "gemini"


def dialog_tts_characters(dialog: str) -> int:
    """Characters ElevenLabs bills for a dialog: the spoken text of each line, without the speaker prefix."""
    return sum(len(line.partition(":")[2].strip()) for line in dialog.splitlines() if line.strip())


def dialog_usage_event(
    settings: Settings,
    *,
    user_id: int,
    lesson_id: str | None,
    model: str | None,
    dialog: str,
    elapsed_ms: int,
) -> dict | None:
    """`LessonAudio` usage row for an ElevenLabs dialog (priced by `per_1k_characters`); None for Gemini."""
    if not is_elevenlabs_model(model):
        return None
    from .speech_clients import speech_usage_event

    return speech_usage_event(
        settings,
        user_id=user_id,
        lesson_id=lesson_id or "custom_tts",
        request_name="dialog_tts",
        model=str(model),
        elapsed_ms=elapsed_ms,
        characters=dialog_tts_characters(dialog),
        request_role="LessonAudio",
    )


def dialog_voice_config_version(settings: Settings) -> str:
    """Voice part of the audio recipe. Fixed ElevenLabs voices are named by ID, so a voice change regenerates audio.

    Random voices are one recipe for every lesson: the pick depends only on the dialogue, which is already in the
    content hash. Adding a voice to the bank therefore does not regenerate existing audio; new audio uses the
    larger pool.
    """
    if is_elevenlabs_model(settings.lesson_tts_model):
        if settings.lesson_tts_random_voices:
            return "elevenlabs_random_anna-f_erik-m_v1"
        return f"elevenlabs_anna-{settings.lesson_tts_anna_voice_id}_erik-{settings.lesson_tts_erik_voice_id}_v1"
    return settings.lesson_tts_voice_config_version


def dialog_voices(settings: Settings, dialog: str) -> dict[str, tuple[str, str]]:
    """Speaker -> (bank name, voice ID). Random mode picks from a hash of the dialogue, so retries match."""
    if not settings.lesson_tts_random_voices:
        return {
            "Anna": ("fixed", settings.lesson_tts_anna_voice_id),
            "Erik": ("fixed", settings.lesson_tts_erik_voice_id),
        }
    digest = hashlib.sha256(dialog.encode("utf-8")).digest()
    anna = _weighted_pick(_role_voice_probabilities("_f"), int.from_bytes(digest[:8], "big") / 2**64)
    erik = _weighted_pick(_role_voice_probabilities("_m"), int.from_bytes(digest[8:16], "big") / 2**64)
    return {"Anna": (anna, ELEVENLABS_VOICES[anna]), "Erik": (erik, ELEVENLABS_VOICES[erik])}


def _role_voice_probabilities(suffix: str) -> dict[str, float]:
    """Pick probability per non-excluded bank voice of one role: DIALOG_RANDOM_VOICE_WEIGHTS where set, the rest of
    the probability split evenly across the role's other voices. Normalized if the fixed shares cannot add up to 1."""
    names = sorted(
        name for name in ELEVENLABS_VOICES if name.endswith(suffix) and name not in DIALOG_RANDOM_EXCLUDED_VOICES
    )
    fixed = {name: DIALOG_RANDOM_VOICE_WEIGHTS[name] for name in names if name in DIALOG_RANDOM_VOICE_WEIGHTS}
    others = [name for name in names if name not in fixed]
    remaining = max(0.0, 1.0 - sum(fixed.values()))
    probabilities = {**fixed, **{name: remaining / len(others) for name in others}} if others else dict(fixed)
    total = sum(probabilities.values())
    if not names or total <= 0:
        raise ValueError(f"No dialog voices available for role {suffix!r}.")
    return {name: probabilities[name] / total for name in names}


def _weighted_pick(probabilities: dict[str, float], u: float) -> str:
    """The voice whose cumulative probability range holds u (0 <= u < 1), in sorted name order."""
    cumulative = 0.0
    for name, probability in probabilities.items():
        cumulative += probability
        if u < cumulative:
            return name
    return next(reversed(probabilities))


async def generate_dialog_wav(settings: Settings, *, dialog: str, model: str | None = None) -> bytes:
    selected = model or GEMINI_DEFAULT_MODEL
    if is_elevenlabs_model(selected):
        return await _generate_elevenlabs_wav(settings, dialog=dialog, model=selected)
    return await generate_gemini_wav(settings, dialog=dialog, model=selected)


def _dialog_lines(voices: dict[str, tuple[str, str]], dialog: str) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    for raw in dialog.splitlines():
        if not raw.strip():
            continue
        speaker, separator, text = raw.partition(":")
        voice = voices.get(speaker.strip())
        if not separator or voice is None or not text.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Dialog lines must look like 'Anna: …' or 'Erik: …'.",
            )
        lines.append((voice[1], text.strip()))
    if not lines:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Dialog is empty.")
    return lines


def _level_voices(
    voices: dict[str, tuple[str, str]], lines: list[tuple[str, str]], chunks: list[bytes]
) -> list[bytes]:
    """Loudness match: all lines of one voice share one gain, and every voice lands on one common level (the target,
    or lower when a voice cannot reach it even with DIALOG_LIMITER_MAX_DB of peaks shaved). A lookahead limiter then
    keeps every line at or below DIALOG_PEAK_CEILING_DBFS."""
    names = {voice_id: name for name, voice_id in voices.values()}
    groups = {
        voice_id: [i for i, (line_voice, _) in enumerate(lines) if line_voice == voice_id]
        for voice_id in dict.fromkeys(voice_id for voice_id, _ in lines)
    }
    levels = {voice_id: measure([chunks[i] for i in indexes], 24_000) for voice_id, indexes in groups.items()}
    common, gains = shared_level_gains(
        levels,
        target_lufs=DIALOG_TARGET_LUFS,
        peak_ceiling_dbfs=DIALOG_PEAK_CEILING_DBFS + DIALOG_LIMITER_MAX_DB,
    )
    for voice_id, indexes in groups.items():
        leveled = apply_gain(
            [chunks[i] for i in indexes], gains[voice_id], 24_000,
            ceiling_dbfs=DIALOG_PEAK_CEILING_DBFS, lookahead_seconds=DIALOG_LIMITER_LOOKAHEAD_SECONDS,
        )
        for i, chunk in zip(indexes, leveled):
            chunks[i] = chunk
        lufs, peak = levels[voice_id]
        logger.info(
            "dialog_tts_loudness voice=%s measured_lufs=%s peak_dbfs=%s gain_db=%.1f common_lufs=%s",
            names.get(voice_id, voice_id),
            "n/a" if lufs is None else f"{lufs:.1f}",
            "n/a" if peak is None else f"{peak:.1f}",
            gains[voice_id],
            "n/a" if common is None else f"{common:.1f}",
        )
    return chunks


async def _generate_elevenlabs_wav(settings: Settings, *, dialog: str, model: str) -> bytes:
    if not settings.elevenlabs_api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ElevenLabs is not configured.")
    voices = dialog_voices(settings, dialog)
    lines = _dialog_lines(voices, dialog)
    semaphore = asyncio.Semaphore(MAX_PARALLEL_LINE_REQUESTS)

    async with httpx.AsyncClient(timeout=settings.gemini_timeout_seconds) as client:

        async def synthesize(voice_id: str, text: str) -> bytes:
            async with semaphore:
                response = await client.post(
                    ELEVENLABS_TTS_URL.format(voice_id=voice_id),
                    params={"output_format": ELEVENLABS_PCM_OUTPUT_FORMAT},
                    headers={"xi-api-key": settings.elevenlabs_api_key},
                    json={"text": text, "model_id": model, "language_code": "sv"},
                )
            if response.status_code != 200:
                logger.warning(
                    "dialog_tts_elevenlabs_failed status=%s voice_id=%s request_id=%s body=%s",
                    response.status_code,
                    voice_id,
                    response.headers.get("request-id"),
                    response.text[:500].replace("\n", " "),
                )
                if response.status_code == 429:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="ElevenLabs rate limited the audio request.",
                    )
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="ElevenLabs audio generation failed.")
            pcm = response.content
            return pcm[: len(pcm) - len(pcm) % 2]

        chunks = await asyncio.gather(*(synthesize(voice_id, text) for voice_id, text in lines))

    if not all(chunks):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="ElevenLabs returned no audio.")
    chunks = _level_voices(voices, lines, list(chunks))
    pause =b"\x00" * (int(PCM_BYTES_PER_SECOND * LINE_PAUSE_SECONDS) // 2 * 2)
    logger.info(
        "dialog_tts_elevenlabs_succeeded model=%s anna=%s erik=%s lines=%s characters=%s",
        model,
        voices["Anna"][0],
        voices["Erik"][0],
        len(lines),
        sum(len(text) for _, text in lines),
    )
    return build_wav_from_pcm(pause.join(chunks))
