from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from .anthropic_client import send_structured_anthropic_request
from .config import REPO_ROOT, Settings
from .learning_catalog import CatalogLesson
from .openai_client import UsageRecorder, canonical_json, logger, response_input_item, send_structured_request
from .speaking_service import SPEAKER_TARGET_REPLIES, SpeakingContextError


PLAN_CREATOR_PROMPT_PATH = REPO_ROOT / "Materials" / "Speaking_plan_creator_prompt.md"
PLANNED_SPEAKER_PROMPT_PATH = REPO_ROOT / "Materials" / "Speaker_planned_prompt.md"
# Bump when plan generation changes in a way the prompt, schema, model and lesson payload don't capture.
SPEAKING_PLAN_RECIPE_VERSION = "speaking_plan_v2"
# Loose topics the conversation can move through, not one step per learner reply.
SPEAKING_PLAN_TOPICS = 4
SPEAKING_PLAN_TIMEOUT_SECONDS = 180.0


def _string(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _strings(description: str) -> dict[str, Any]:
    return {"type": "array", "description": description, "items": {"type": "string"}}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def speaking_plan_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "speaking_plan",
        "strict": True,
        "schema": _object(
            {
                "language": _object(
                    {
                        "level": _string("Elevens nivå."),
                        "guidance": _string("Hur läraren ska tala."),
                        "useful_phrases": _strings("Ord och fraser från lektionen."),
                    }
                ),
                "scene": _object(
                    {
                        "setting": _string("Var och när."),
                        "tutor_role": _string("Vem läraren är."),
                        "learner_role": _string("Vem eleven är i scenen."),
                        "established_facts": _strings("Det som är sant från början."),
                    }
                ),
                "target_form": _object(
                    {
                        "name": _string("Målformens namn."),
                        "explanation": _string("Kort förklaring att bedöma fel mot."),
                        "examples": _strings("Två eller tre korta exempel."),
                    }
                ),
                "opening": _string("En mening som sätter scenen."),
                "topics": {
                    "type": "array",
                    "description": f"Exakt {SPEAKING_PLAN_TOPICS} ämnen i ungefärlig ordning.",
                    "items": _object(
                        {
                            "focus": _string("Vad ämnet handlar om."),
                            "uses_target_form": {"type": "boolean"},
                        }
                    ),
                },
                "closing": _string("Hur läraren avslutar."),
            }
        ),
    }


def _creator_prompt(prompt_path: Path = PLAN_CREATOR_PROMPT_PATH) -> str:
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise SpeakingContextError("Speaking plan creator prompt is empty.")
    return prompt


def creator_lesson_payload(lesson: CatalogLesson) -> dict[str, Any]:
    """The lesson as the creator sees it: without the reading dialogue's opening/middle/ending script,
    which otherwise makes the plan assume what the learner will answer. Its target complexity stays."""
    payload = dict(lesson.payload)
    shape = payload.pop("dialogue_shape", None)
    if isinstance(shape, dict) and "target_complexity" in shape:
        payload["dialogue_shape"] = {"target_complexity": shape["target_complexity"]}
    return payload


def speaking_plan_fingerprint(lesson: CatalogLesson, settings: Settings) -> str:
    recipe = {
        "recipe_version": SPEAKING_PLAN_RECIPE_VERSION,
        "lesson_payload": creator_lesson_payload(lesson),
        "creator_prompt": _creator_prompt(),
        "schema": speaking_plan_schema(),
        "model": settings.speaking_plan_model,
        "reasoning_effort": settings.speaking_plan_reasoning_effort,
        "topics": SPEAKING_PLAN_TOPICS,
        "replies": SPEAKER_TARGET_REPLIES,
    }
    return hashlib.sha256(canonical_json(recipe).encode("utf-8")).hexdigest()


def validate_speaking_plan(plan: dict[str, Any]) -> dict[str, Any]:
    topics = plan.get("topics")
    if not isinstance(topics, list) or len(topics) != SPEAKING_PLAN_TOPICS:
        raise SpeakingContextError(f"Speaking plan must have exactly {SPEAKING_PLAN_TOPICS} topics.")
    for topic in topics:
        if not str(topic.get("focus", "")).strip():
            raise SpeakingContextError("Speaking plan has an empty topic.")
    for key in ("opening", "closing"):
        if not str(plan.get(key, "")).strip():
            raise SpeakingContextError(f"Speaking plan has an empty {key}.")
    return plan


def build_planned_speaker_instructions(
    plan: dict[str, Any],
    *,
    prompt_path: Path = PLANNED_SPEAKER_PROMPT_PATH,
) -> str:
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise SpeakingContextError("Planned Speaker prompt is empty.")
    numbered = {
        **plan,
        "topics": [{"topic": index, **topic} for index, topic in enumerate(plan["topics"], start=1)],
    }
    return f"{prompt}\n\n=== SPEAKING_PLAN ===\n{json.dumps(numbered, ensure_ascii=False, indent=2)}"


async def generate_speaking_plan(
    settings: Settings,
    *,
    lesson: CatalogLesson,
    user_id: int,
    usage_recorder: UsageRecorder | None = None,
) -> dict[str, Any]:
    model = settings.speaking_plan_model
    instructions = _creator_prompt()
    lesson_json = json.dumps(creator_lesson_payload(lesson), ensure_ascii=False, indent=2)
    if model.strip().lower().startswith("claude-"):
        plan = await send_structured_anthropic_request(
            settings,
            user_id=user_id,
            request_role="SpeakingPlan",
            request_name="speaking_plan",
            prompt_version=SPEAKING_PLAN_RECIPE_VERSION,
            source_id=lesson.lesson_id,
            model=model,
            reasoning_effort=settings.speaking_plan_reasoning_effort,
            instructions=instructions,
            user_text=f"LESSON_JSON:\n{lesson_json}",
            schema=speaking_plan_schema(),
            max_tokens=16_000,
            timeout_seconds=SPEAKING_PLAN_TIMEOUT_SECONDS,
            usage_recorder=usage_recorder,
        )
    else:
        plan = await send_structured_request(
            settings,
            request_role="SpeakingPlan",
            user_id=user_id,
            request_name="speaking_plan",
            lesson_id=lesson.lesson_id,
            model=model,
            reasoning_effort=settings.speaking_plan_reasoning_effort,
            instructions=instructions,
            input_value=[response_input_item("LESSON_JSON", lesson_json)],
            schema=speaking_plan_schema(),
            max_output_tokens=16_000,
            prompt_version=SPEAKING_PLAN_RECIPE_VERSION,
            usage_recorder=usage_recorder,
        )
    return validate_speaking_plan(plan)


class SpeakingPlanGenerator:
    """Process-local: at most one plan generation per lesson recipe, shared by every learner who starts meanwhile.

    Generation runs as its own task so it finishes and is stored even if the learner who triggered it gives up.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}
        self._started: dict[str, float] = {}

    def ensure(self, fingerprint: str, generate: Callable[[], Awaitable[dict[str, Any]]]) -> asyncio.Task[dict[str, Any]]:
        task = self._tasks.get(fingerprint)
        if task is None or task.done():
            task = asyncio.create_task(generate())
            self._tasks[fingerprint] = task
            self._started[fingerprint] = time.monotonic()
            task.add_done_callback(lambda finished: self._finished(fingerprint, finished))
        return task

    def is_running(self, fingerprint: str) -> bool:
        task = self._tasks.get(fingerprint)
        return task is not None and not task.done()

    def running_seconds(self, fingerprint: str) -> float:
        """How long the current generation for this recipe has been running (0 if none)."""
        started = self._started.get(fingerprint)
        return time.monotonic() - started if started is not None else 0.0

    def _finished(self, fingerprint: str, task: asyncio.Task[dict[str, Any]]) -> None:
        if self._tasks.get(fingerprint) is task:
            self._tasks.pop(fingerprint, None)
            self._started.pop(fingerprint, None)
        if not task.cancelled() and task.exception() is not None:
            logger.warning(
                "speaking_plan_failed fingerprint=%s error_type=%s error=%s",
                fingerprint[:12],
                type(task.exception()).__name__,
                str(task.exception())[:300],
            )


async def generate_and_store_speaking_plan(
    settings: Settings,
    *,
    database: Any,
    lesson: CatalogLesson,
    fingerprint: str,
    user_id: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    plan = await generate_speaking_plan(
        settings,
        lesson=lesson,
        user_id=user_id,
        usage_recorder=database.record_openai_usage,
    )
    stored = database.store_speaking_plan(
        lesson_id=lesson.lesson_id,
        recipe_fingerprint=fingerprint,
        plan=plan,
        model=settings.speaking_plan_model,
    )
    logger.info(
        "speaking_plan_generated lesson_id=%s fingerprint=%s model=%s elapsed_ms=%s",
        lesson.lesson_id,
        fingerprint[:12],
        settings.speaking_plan_model,
        int((time.perf_counter() - started) * 1000),
    )
    return stored
