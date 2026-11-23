"""English translation of the tutor's latest line in Speaking practice.

The translation starts as soon as the tutor's reply text exists, in parallel with its speech, so it is
usually ready before the learner taps the translate key; the endpoint then only returns the finished task.
"""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import HTTPException, status

from .config import REPO_ROOT, Settings
from .openai_client import UsageRecorder, send_text_request

logger = logging.getLogger(__name__)

TRANSLATION_PROMPT_PATH = REPO_ROOT / "Materials" / "Speaker_translation_prompt.md"
TRANSLATION_PROMPT_CACHE_KEY = "svenska_speaker_translation_v1"
MAX_TRANSLATION_CHARACTERS = 2_000


async def translate_tutor_line(
    settings: Settings,
    *,
    user_id: int,
    lesson_id: str,
    text: str,
    usage_recorder: UsageRecorder | None,
) -> str:
    if not settings.openai_api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OpenAI is not configured.")
    instructions = TRANSLATION_PROMPT_PATH.read_text(encoding="utf-8").strip()
    started = time.perf_counter()
    output = await send_text_request(
        settings,
        request_role="Speaking",
        user_id=user_id,
        request_name="speaker_translation",
        lesson_id=lesson_id,
        model=settings.speaker_translation_model,
        reasoning_effort=settings.speaker_translation_reasoning_effort,
        instructions=instructions,
        input_value=[{"role": "user", "content": text}],
        schema={"type": "text"},
        max_output_tokens=2_000,
        prompt_cache_key=TRANSLATION_PROMPT_CACHE_KEY,
        prompt_version="speaker_translation_v1",
        usage_recorder=usage_recorder,
    )
    translation = " ".join(output.split()).strip('"“”')
    if not translation:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The translation was empty.")
    logger.info(
        "speaking_translation user_id=%s lesson_id=%s model=%s llm_ms=%s",
        user_id,
        lesson_id,
        settings.speaker_translation_model,
        int((time.perf_counter() - started) * 1000),
    )
    return translation[:MAX_TRANSLATION_CHARACTERS]


def start_tutor_translation(
    settings: Settings,
    *,
    user_id: int,
    lesson_id: str,
    text: str,
    usage_recorder: UsageRecorder | None,
) -> asyncio.Task[str]:
    """Starts the translation in the background; a failure is logged here and retried on request."""
    task = asyncio.create_task(
        translate_tutor_line(settings, user_id=user_id, lesson_id=lesson_id, text=text, usage_recorder=usage_recorder)
    )

    def _log_failure(done: asyncio.Task[str]) -> None:
        if done.cancelled():
            return
        error = done.exception()
        if error is not None:
            logger.warning(
                "speaking_translation_failed user_id=%s lesson_id=%s error_type=%s detail=%s",
                user_id,
                lesson_id,
                type(error).__name__,
                getattr(error, "detail", ""),
            )

    task.add_done_callback(_log_failure)
    return task
