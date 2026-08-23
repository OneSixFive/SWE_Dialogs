from __future__ import annotations

import asyncio
import logging
import os
import random
import tempfile
import time

import httpx
from fastapi import HTTPException

from .config import Settings
from .db import ArtifactAudioJob, Database, LessonAudioJob
from .gemini_client import generate_wav
from .lesson_audio import canonical_tts_text
from .lesson_artifacts import artifact_audio_identity, shared_audio_relative_path


logger = logging.getLogger("uvicorn.error")
MAX_LESSON_AUDIO_BYTES = 25 * 1024 * 1024


async def process_one_lesson_audio(database: Database, settings: Settings) -> bool:
    artifact_job = database.claim_artifact_audio_job(lease_seconds=settings.lesson_audio_lease_seconds)
    if artifact_job is not None:
        await _process_artifact_audio_job(database, settings, artifact_job)
        return True

    job = database.claim_lesson_audio_job(lease_seconds=settings.lesson_audio_lease_seconds)
    if job is None:
        return False

    started = time.monotonic()
    prefix = job.content_hash[:12]
    logger.info(
        "lesson_audio_job_claimed user_id=%s lesson_id=%s content_hash=%s job_id=%s attempt=%s model=%s voice_config=%s",
        job.user_id, job.lesson_id, prefix, job.id, job.attempt_count, job.model, job.voice_config_version,
    )
    identity = database.current_lesson_audio_identity(user_id=job.user_id, lesson_id=job.lesson_id)
    if identity is None or identity[1] != job.content_hash:
        database.supersede_lesson_audio_job(job.id)
        logger.info(
            "lesson_audio_superseded user_id=%s lesson_id=%s content_hash=%s job_id=%s",
            job.user_id, job.lesson_id, prefix, job.id,
        )
        return True

    try:
        dialog = canonical_tts_text(identity[0])
        wav_data = await generate_wav(settings, dialog=dialog, model=job.model)
        _validate_wav(wav_data)
        stored = database.complete_lesson_audio_job(job=job, audio_data=wav_data)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if stored:
            logger.info(
                "lesson_audio_provider_succeeded user_id=%s lesson_id=%s content_hash=%s job_id=%s attempt=%s model=%s voice_config=%s elapsed_ms=%s bytes=%s",
                job.user_id, job.lesson_id, prefix, job.id, job.attempt_count, job.model,
                job.voice_config_version, elapsed_ms, len(wav_data),
            )
        else:
            logger.info(
                "lesson_audio_superseded user_id=%s lesson_id=%s content_hash=%s job_id=%s elapsed_ms=%s",
                job.user_id, job.lesson_id, prefix, job.id, elapsed_ms,
            )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        error_code, summary, retryable = _classify_error(error)
        delay = _retry_delay(job)
        next_status = database.fail_lesson_audio_job(
            job=job,
            error_code=error_code,
            error_summary=summary,
            retryable=retryable,
            max_attempts=settings.lesson_audio_max_attempts,
            retry_delay_seconds=delay,
        )
        event = "lesson_audio_retry_scheduled" if next_status == "pending" else "lesson_audio_failed"
        logger.warning(
            "%s user_id=%s lesson_id=%s content_hash=%s job_id=%s attempt=%s model=%s voice_config=%s error_code=%s retryable=%s",
            event, job.user_id, job.lesson_id, prefix, job.id, job.attempt_count, job.model,
            job.voice_config_version, error_code, retryable,
        )
    return True


async def _process_artifact_audio_job(
    database: Database, settings: Settings, job: ArtifactAudioJob
) -> None:
    started = time.monotonic()
    prefix = job.content_hash[:12]
    artifact = database.get_lesson_artifact(job.lesson_artifact_id)
    if artifact is None:
        database.supersede_artifact_audio_job(job.id)
        return
    dialogue_hash, content_hash, recipe = artifact_audio_identity(settings, artifact.generated_lesson)
    if (
        dialogue_hash != job.dialogue_text_hash
        or content_hash != job.content_hash
        or recipe.fingerprint != job.audio_recipe_fingerprint
    ):
        database.supersede_artifact_audio_job(job.id)
        logger.info(
            "artifact_audio_superseded lesson_id=%s artifact_id=%s content_hash=%s job_id=%s",
            job.lesson_id, job.lesson_artifact_id, prefix, job.id,
        )
        return
    try:
        wav_data = await generate_wav(
            settings,
            dialog=canonical_tts_text(artifact.generated_lesson),
            model=job.model,
        )
        _validate_wav(wav_data)
        root = settings.shared_audio_directory or (settings.database_path.parent / "shared_lesson_audio")
        relative_path = shared_audio_relative_path(job.content_hash)
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".lesson-audio-", dir=destination.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(wav_data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        stored = database.complete_artifact_audio_job(
            job=job,
            relative_file_path=str(relative_path),
            byte_count=len(wav_data),
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "artifact_audio_provider_succeeded lesson_id=%s artifact_id=%s content_hash=%s "
            "job_id=%s stored=%s elapsed_ms=%s bytes=%s",
            job.lesson_id, job.lesson_artifact_id, prefix, job.id, stored, elapsed_ms, len(wav_data),
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        error_code, summary, retryable = _classify_error(error)
        next_status = database.fail_artifact_audio_job(
            job=job,
            error_code=error_code,
            error_summary=summary,
            retryable=retryable,
            max_attempts=settings.lesson_audio_max_attempts,
            retry_delay_seconds=_retry_delay(job),
        )
        logger.warning(
            "artifact_audio_job_failed lesson_id=%s artifact_id=%s content_hash=%s "
            "job_id=%s status=%s error_code=%s retryable=%s",
            job.lesson_id, job.lesson_artifact_id, prefix, job.id, next_status, error_code, retryable,
        )


async def lesson_audio_worker_loop(database: Database, settings: Settings) -> None:
    while True:
        try:
            processed = await process_one_lesson_audio(database, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("lesson_audio_worker_iteration_failed")
            processed = False
        if not processed:
            await asyncio.sleep(settings.lesson_audio_worker_interval_seconds)


def _validate_wav(data: bytes) -> None:
    if not data or len(data) < 44 or not data.startswith(b"RIFF") or data[8:12] != b"WAVE":
        raise ValueError("invalid_wav")
    if len(data) > MAX_LESSON_AUDIO_BYTES:
        raise ValueError("audio_too_large")


def _retry_delay(job: LessonAudioJob | ArtifactAudioJob) -> float:
    base = min(15 * (2 ** max(job.attempt_count - 1, 0)), 300)
    return base + random.uniform(0, min(base * 0.2, 15))


def _classify_error(error: Exception) -> tuple[str, str, bool]:
    if isinstance(error, (httpx.TimeoutException, TimeoutError)):
        return "provider_timeout", "Audio provider timed out.", True
    if isinstance(error, httpx.NetworkError):
        return "provider_network", "Audio provider network error.", True
    if isinstance(error, HTTPException):
        if error.status_code == 429:
            return "provider_rate_limited", "Audio provider rate limited the request.", True
        if error.status_code >= 500:
            return "provider_error", "Audio provider returned an error.", True
        return "invalid_request", "Audio request was rejected.", False
    if isinstance(error, ValueError):
        code = str(error) if str(error) in {"invalid_wav", "audio_too_large"} else "invalid_dialogue"
        return code, "Generated audio or dialogue failed validation.", False
    return "unexpected_error", "Unexpected audio generation error.", True
