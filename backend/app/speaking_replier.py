"""Replier: on request, suggests what the learner could say next to the tutor's latest line.

It runs only when the learner taps the hint key, but its input is kept ready: the system prompt is built
when the Speaker's instructions are, and each committed turn appends its lines to
`SpeakerConversation.replier_lines`, so a request only adds the closing ask. The prefix (prompt, lesson,
then the append-only conversation lines) stays byte-stable from hint to hint for prompt caching.
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import HTTPException, status

from .anthropic_client import _client, _create, _effort, _log_anthropic_usage
from .config import REPO_ROOT, Settings
from .learning_catalog import CatalogLesson
from .openai_client import UsageRecorder, scoped_prompt_cache_key, send_text_request
from .speaking_plans import planned_lesson_context
from .speaking_service import SpeakerConversation, SpeakingContextError

REPLIER_PROMPT_PATH = REPO_ROOT / "Materials" / "Speaker_replier_prompt.md"
REPLIER_PROMPT_CACHE_KEY = "svenska_speaker_replier_v1"
REPLIER_ASK = "Write the learner's reply to the tutor's last line."
MAX_REPLIER_CHARACTERS = 600


def _is_anthropic(model: str) -> bool:
    return model.strip().lower().startswith("claude-")


def build_replier_instructions(lesson: CatalogLesson, plan: dict[str, Any] | None) -> str:
    """Prompt, the lesson's level/targets/vocabulary, and the scene (the plan's, or the curriculum scenario)."""
    prompt = REPLIER_PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not prompt:
        raise SpeakingContextError("Speaker_replier_prompt.md is empty.")
    lesson_context = planned_lesson_context(lesson)
    if plan is not None:
        scene: dict[str, Any] = dict(plan["scene"])
    else:
        scene = {"scenario": (lesson.payload.get("dialogue_task") or {}).get("scenario")}
    return (
        f"{prompt}\n\n=== LESSON ===\n{json.dumps(lesson_context, ensure_ascii=False, indent=2)}"
        f"\n\n=== SCENE ===\n{json.dumps(scene, ensure_ascii=False, indent=2)}"
    )


async def suggest_reply(
    settings: Settings,
    *,
    user_id: int,
    lesson_id: str,
    conversation: SpeakerConversation,
    usage_recorder: UsageRecorder | None,
) -> str:
    instructions = conversation.replier_instructions
    lines = list(conversation.replier_lines)
    if not instructions or not lines:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="There is nothing to reply to yet.")
    model = settings.speaker_replier_model
    if _is_anthropic(model):
        if not settings.anthropic_api_key:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Anthropic is not configured.")
        text = await _suggest_anthropic(settings, user_id=user_id, lesson_id=lesson_id, model=model,
                                        instructions=instructions, lines=lines, usage_recorder=usage_recorder)
    else:
        if not settings.openai_api_key:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OpenAI is not configured.")
        text = await send_text_request(
            settings,
            request_role="Speaking",
            user_id=user_id,
            request_name="speaker_replier",
            lesson_id=lesson_id,
            model=model,
            reasoning_effort=settings.speaker_replier_reasoning_effort,
            instructions=instructions,
            input_value=[
                *({"role": "user", "content": line} for line in lines),
                {"role": "developer", "content": REPLIER_ASK},
            ],
            schema={"type": "text"},
            max_output_tokens=2_000,
            prompt_cache_key=scoped_prompt_cache_key(REPLIER_PROMPT_CACHE_KEY, lesson_id),
            prompt_version="speaker_replier_v1",
            usage_recorder=usage_recorder,
        )
    reply = " ".join(text.split()).strip('"“”„ ')
    if not reply:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The suggested reply was empty.")
    return reply[:MAX_REPLIER_CHARACTERS]


async def _suggest_anthropic(
    settings: Settings,
    *,
    user_id: int,
    lesson_id: str,
    model: str,
    instructions: str,
    lines: list[str],
    usage_recorder: UsageRecorder | None,
) -> str:
    content: list[dict[str, Any]] = [{"type": "text", "text": line} for line in lines]
    content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
    content.append({"type": "text", "text": REPLIER_ASK})
    started = time.perf_counter()
    response = await _create(
        _client(settings.anthropic_api_key, settings.speaker_provider_timeout_seconds).messages.create(
            model=model,
            max_tokens=2_000,
            system=[{"type": "text", "text": instructions, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
            output_config={"effort": _effort(settings.speaker_replier_reasoning_effort)},
        )
    )
    usage_event = _log_anthropic_usage(
        settings,
        user_id=user_id,
        request_role="Speaking",
        request_name="speaker_replier",
        prompt_version="speaker_replier_v1",
        source_id=lesson_id,
        model=model,
        instructions=instructions,
        input_messages=1,
        response=response,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
    if usage_event is not None and usage_recorder is not None:
        usage_recorder(usage_event)
    return "".join(block.text for block in response.content if block.type == "text")
