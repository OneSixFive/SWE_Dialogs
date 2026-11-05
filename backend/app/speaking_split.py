"""Split Speaker: per learner reply, a checker judges the sentence while a conversationalist just talks.

Both run in parallel, each on its own model (`speaker_conversation_model`, `speaker_check_model`); a
`claude-*` name goes to Anthropic, anything else to the OpenAI Responses API. A correction is a fixed template built from the checker's sentence; the
conversationalist never sees corrections, only the sentences finally accepted, so its history reads
like a plain conversation. Reply counting and the end of the practice stay in SpeakerConversation.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from fastapi import HTTPException, status

from .anthropic_client import (
    _client,
    _create,
    _effort,
    _log_anthropic_usage,
    _replay_block,
    _structured_output,
)
from .config import REPO_ROOT, Settings
from .learning_catalog import CatalogLesson
from .openai_client import (
    UsageRecorder,
    logger,
    scoped_prompt_cache_key,
    send_structured_request,
    send_text_request,
)
from .speaking_plans import planned_lesson_context
from .speaking_service import SPEAKER_TARGET_REPLIES, SpeakerConversation, SpeakingContextError

CONVERSATION_PROMPT_PATH = REPO_ROOT / "Materials" / "Speaker_conversation_prompt.md"
CHECK_PROMPT_PATH = REPO_ROOT / "Materials" / "Speaker_check_prompt.md"
OPENING_USER_TEXT = "(The practice begins. The learner has not said anything yet.)"
OPENING_NOTE = "Open the chat with a short greeting, starting from the first topic. End with something the learner can answer."
MISHEARD_SAY = "Förlåt, jag hörde inte riktigt. Kan du säga det igen?"
MAX_REPEAT_REQUESTS = 2
CONVERSATION_PROMPT_CACHE_KEY = "svenska_speaker_conversation_v1"
CHECK_PROMPT_CACHE_KEY = "svenska_speaker_check_v1"

CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "needs_correction", "corrected_sentence", "misheard"],
    "properties": {
        "kind": {"type": "string", "enum": ["answer", "help", "unclear"]},
        "needs_correction": {"type": "boolean"},
        "corrected_sentence": {"type": "string"},
        "misheard": {"type": "boolean"},
    },
}


def _is_anthropic(model: str) -> bool:
    return model.strip().lower().startswith("claude-")


def _read_prompt(path: Any) -> str:
    prompt = path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise SpeakingContextError(f"{path.name} is empty.")
    return prompt


def build_split_instructions(plan: dict[str, Any], lesson: CatalogLesson) -> str:
    """The conversationalist's system prompt: no target form, examples or drill fields, only level and scene."""
    context = planned_lesson_context(lesson)
    learner = {
        "level": context["level"],
        "avoid_grammar": context["avoid_grammar"],
        "style": "Short, simple sentences.",
    }
    scene = {**plan["scene"], "topics": [topic["focus"] for topic in plan["topics"]]}
    return (
        f"{_read_prompt(CONVERSATION_PROMPT_PATH)}\n\n=== LEARNER ===\n{json.dumps(learner, ensure_ascii=False, indent=2)}"
        f"\n\n=== SCENE ===\n{json.dumps(scene, ensure_ascii=False, indent=2)}"
    )


_METADATA_LINE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\s*:\s*\S*")


def _spoken_text(text: str, *, lesson_id: str) -> str:
    """Text for speech synthesis: drop stray leading `key: value` lines (seen once as "reasoning_effort: 5")
    and collapse the blank lines the model sometimes puts between sentences."""
    lines = text.strip().splitlines()
    dropped = []
    while lines and (not lines[0].strip() or _METADATA_LINE.fullmatch(lines[0].strip())):
        dropped.append(lines.pop(0).strip())
    if any(dropped):
        logger.warning("speaker_conversation_metadata_dropped lesson_id=%s lines=%s", lesson_id, [line for line in dropped if line])
    return " ".join(" ".join(lines).split())


def _turn_note(reply_number: int) -> str:
    left = SPEAKER_TARGET_REPLIES - reply_number
    if left <= 0:
        return (
            "That was the last reply from the learner. Respond to it and say goodbye, "
            "in at most three short sentences and with no question."
        )
    return (
        f"Learner reply {reply_number} of {SPEAKER_TARGET_REPLIES}; {left} left. "
        "The chat continues after this turn: end with something the learner can answer."
    )


async def _converse(
    settings: Settings,
    *,
    user_id: int,
    lesson_id: str,
    instructions: str,
    history: list[dict[str, Any]],
    user_text: str,
    note: str,
    usage_recorder: UsageRecorder | None,
) -> tuple[str, list[dict[str, Any]]]:
    """The tutor's reply and the messages to append to its history, in the provider's own message format.
    History is append-only so each turn reads back the previous turn's cached prefix."""
    model = settings.speaker_conversation_model
    if not _is_anthropic(model):
        user_message = {"role": "user", "content": user_text}
        note_message = {"role": "developer", "content": note}
        text = await send_text_request(
            settings,
            request_role="Speaking",
            user_id=user_id,
            request_name="speaker_conversation",
            lesson_id=lesson_id,
            model=model,
            reasoning_effort=settings.speaker_conversation_reasoning_effort,
            instructions=instructions,
            input_value=[*history, user_message, note_message],
            schema={"type": "text"},
            max_output_tokens=2_000,
            prompt_cache_key=scoped_prompt_cache_key(CONVERSATION_PROMPT_CACHE_KEY, lesson_id),
            prompt_version="speaker_split_v1",
            usage_recorder=usage_recorder,
        )
        say = _spoken_text(text, lesson_id=lesson_id)
        if not say:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The tutor reply was empty.")
        return say, [user_message, note_message, {"role": "assistant", "content": say}]

    user_message = {"role": "user", "content": [{"type": "text", "text": user_text}]}
    cached_user_message = {"role": "user", "content": [{"type": "text", "text": user_text, "cache_control": {"type": "ephemeral"}}]}
    note_message = {"role": "system", "content": note}
    messages = [*history, cached_user_message, note_message]
    started = time.perf_counter()
    response = await _create(
        _client(settings.anthropic_api_key, settings.speaker_provider_timeout_seconds).messages.create(
            model=model,
            max_tokens=2_000,
            system=[{"type": "text", "text": instructions, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            output_config={"effort": _effort(settings.speaker_conversation_reasoning_effort)},
        )
    )
    usage_event = _log_anthropic_usage(
        settings,
        user_id=user_id,
        request_role="Speaking",
        request_name="speaker_conversation",
        prompt_version="speaker_split_v1",
        source_id=lesson_id,
        model=model,
        instructions=instructions,
        input_messages=len(messages),
        response=response,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
    if usage_event is not None and usage_recorder is not None:
        usage_recorder(usage_event)
    say = _spoken_text("".join(block.text for block in response.content if block.type == "text"), lesson_id=lesson_id)
    if not say:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The tutor reply was empty.")
    # Replay thinking as returned, but the spoken text as cleaned, so a stray artifact is not echoed in later turns.
    content = [_replay_block(block) for block in response.content if block.type in {"thinking", "redacted_thinking"}]
    content.append({"type": "text", "text": say})
    assistant_message = {"role": "assistant", "content": content}
    return say, [user_message, note_message, assistant_message]


async def _check(
    settings: Settings,
    *,
    user_id: int,
    lesson: CatalogLesson,
    tutor_said: str,
    learner_reply: str,
    requested_sentence: str | None,
    usage_recorder: UsageRecorder | None,
) -> dict[str, Any]:
    context = planned_lesson_context(lesson)
    payload = {
        "learner_level": context["level"],
        "lesson_target_form": context["target_form"],
        "tutor_said": tutor_said,
        "learner_reply": learner_reply,
        "requested_sentence": requested_sentence,
    }
    instructions = _read_prompt(CHECK_PROMPT_PATH)
    model = settings.speaker_check_model
    if not _is_anthropic(model):
        return await send_structured_request(
            settings,
            request_role="Speaking",
            user_id=user_id,
            request_name="speaker_check",
            lesson_id=lesson.lesson_id,
            model=model,
            reasoning_effort=settings.speaker_check_reasoning_effort,
            instructions=instructions,
            input_value=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            schema={"type": "json_schema", "name": "speaker_check", "strict": True, "schema": CHECK_SCHEMA},
            max_output_tokens=8_000,
            prompt_cache_key=CHECK_PROMPT_CACHE_KEY,
            prompt_version="speaker_split_v1",
            usage_recorder=usage_recorder,
        )
    started = time.perf_counter()
    response = await _create(
        _client(settings.anthropic_api_key, settings.speaker_provider_timeout_seconds).messages.create(
            model=model,
            max_tokens=8_000,  # room to finish thinking on hard sentences; 2,000 cut it off
            system=instructions,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            output_config={
                "effort": _effort(settings.speaker_check_reasoning_effort),
                "format": {"type": "json_schema", "schema": CHECK_SCHEMA},
            },
        )
    )
    usage_event = _log_anthropic_usage(
        settings,
        user_id=user_id,
        request_role="Speaking",
        request_name="speaker_check",
        prompt_version="speaker_split_v1",
        source_id=lesson.lesson_id,
        model=model,
        instructions=instructions,
        input_messages=1,
        response=response,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
    if usage_event is not None and usage_recorder is not None:
        usage_recorder(usage_event)
    return _structured_output(response)


async def send_split_turn(
    settings: Settings,
    *,
    user_id: int,
    lesson: CatalogLesson,
    conversation: SpeakerConversation,
    transcript: str | None,
    usage_recorder: UsageRecorder | None = None,
) -> dict[str, Any]:
    """One tutor turn. Returns say/learner_turn/correcting/provider_messages like the single-call Speaker."""
    models = (settings.speaker_conversation_model, settings.speaker_check_model)
    if any(_is_anthropic(model) for model in models) and not settings.anthropic_api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Anthropic is not configured.")
    if not all(_is_anthropic(model) for model in models) and not settings.openai_api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OpenAI is not configured.")
    history = list(conversation.provider_messages)
    if transcript is None:
        say, provider_messages = await _converse(
            settings,
            user_id=user_id,
            lesson_id=lesson.lesson_id,
            instructions=conversation.instructions,
            history=history,
            user_text=OPENING_USER_TEXT,
            note=OPENING_NOTE,
            usage_recorder=usage_recorder,
        )
        return {"say": say, "learner_turn": "opening", "correcting": False, "provider_messages": provider_messages}

    repeating = conversation.correction_pending
    reply_number = conversation.counted_replies + (0 if repeating else 1)
    tutor_said = next(
        (message["content"] for message in reversed(conversation.messages) if message["role"] == "assistant"),
        "",
    )
    # The reply is drafted while the sentence is checked; it is dropped if the turn becomes a correction.
    conversing = asyncio.create_task(
        _converse(
            settings,
            user_id=user_id,
            lesson_id=lesson.lesson_id,
            instructions=conversation.instructions,
            history=history,
            user_text=transcript,
            note=_turn_note(reply_number),
            usage_recorder=usage_recorder,
        )
    )
    try:
        verdict = await _check(
            settings,
            user_id=user_id,
            lesson=lesson,
            tutor_said=tutor_said,
            learner_reply=transcript,
            requested_sentence=conversation.pending_sentence if repeating else None,
            usage_recorder=usage_recorder,
        )
    except BaseException:
        conversing.cancel()
        raise

    kind = verdict.get("kind")
    answer_turn = "correction_repeat" if repeating else "substantive"
    corrected = str(verdict.get("corrected_sentence") or "").strip()
    if kind == "answer" and verdict.get("misheard") is True and conversation.misheard_requests < MAX_REPEAT_REQUESTS:
        conversing.cancel()
        return {"say": MISHEARD_SAY, "learner_turn": "unclear", "correcting": False, "misheard": True, "provider_messages": []}
    if (
        kind == "answer"
        and verdict.get("needs_correction") is True
        and corrected
        and conversation.correction_requests < MAX_REPEAT_REQUESTS
    ):
        conversing.cancel()
        return {
            "say": f'Nästan. Säg: "{corrected}" Försök igen.',
            "learner_turn": answer_turn,
            "correcting": True,
            "requested_sentence": corrected,
            "provider_messages": [],
        }

    say, provider_messages = await conversing
    learner_turn = {"answer": answer_turn, "help": "help_or_clarification"}.get(str(kind), "unclear")
    return {"say": say, "learner_turn": learner_turn, "correcting": False, "provider_messages": provider_messages}
