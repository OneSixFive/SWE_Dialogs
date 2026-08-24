from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any, Callable

import httpx
from fastapi import HTTPException, status

from .config import REPO_ROOT, Settings


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
PROMPTS_DIR = REPO_ROOT / "Materials"
GENERATOR_PROMPT_CACHE_KEY = "svenska_lesson_generator_v1"
INTERACTOR_PROMPT_CACHE_KEY = "svenska_lesson_interactor_v1"
EVALUATOR_PROMPT_CACHE_KEY = "svenska_learning_evaluator_v3"
VOCABULARY_QUIZ_PROMPT_CACHE_KEY = "svenska_vocabulary_quiz_v1"
VOCABULARY_INTERACTOR_PROMPT_CACHE_KEY = "svenska_vocabulary_interactor_v1"
GPT56_PROMPT_CACHE_TTL = "30m"
INTERACTOR_PATCHABLE_PHASES = ["generated", "listening", "comprehension", "discussion", "translation"]
START_TRANSLATION_QUIZ_COMMAND = "SYSTEM_UI_ACTION: start_translation_quiz"
PRE_DISCUSSION_PHASES = {"notStarted", "not_started", "generated", "listening", "comprehension"}
DISCUSSION_STAGE_TEXT_PATTERNS = [
    "du kan nu läsa dialogen",
    "du kan nu lasa dialogen",
    "läs dialogen en gång till",
    "las dialogen en gang till",
    "läsa dialogen igen",
    "lasa dialogen igen",
    "reread the dialog",
    "read the dialog again",
    "fråga om ord, uttryck",
    "fraga om ord, uttryck",
]
logger = logging.getLogger("uvicorn.error")
UsageRecorder = Callable[[dict[str, Any]], None]
ResponseMetadataRecorder = Callable[[dict[str, str | None]], None]


def _read_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


def generator_prompt_sources() -> tuple[str, str]:
    return _read_prompt("Shared_base_prompt"), _read_prompt("Generator_prompt")


def _camel_to_snake(value: str) -> str:
    first = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", value)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", first).lower()


def snake_case_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {_camel_to_snake(str(key)): snake_case_keys(item) for key, item in value.items()}
    if isinstance(value, list):
        return [snake_case_keys(item) for item in value]
    return value


def json_string(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def short_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def json_sha256(value: Any) -> str:
    return short_sha256(canonical_json(value))


def scoped_prompt_cache_key(base_key: str, scope_id: str | None) -> str:
    normalized = str(scope_id or "").strip()
    return f"{base_key}:{short_sha256(normalized)}" if normalized else base_key


def course_context_object(payload: dict[str, Any]) -> dict[str, str]:
    lesson_id = str(payload.get("id", "")).lower()
    if lesson_id.startswith("b2_"):
        return {"course_level": "B2", "explanation_swedish_level": "B1"}
    return {"course_level": "B1", "explanation_swedish_level": "A2"}


def chat_message_objects(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "role": str(message.get("role", "")),
            "content": str(message.get("content", "")),
        }
        for message in messages
    ]


def append_only_history_input_items(
    title: str,
    messages: list[dict[str, Any]],
    *,
    cache_breakpoints: bool,
) -> list[dict[str, Any]]:
    """Render stable history chunks that never change after an assistant turn."""
    normalized_messages = chat_message_objects(messages)
    if not normalized_messages:
        return [response_input_item(title, json_string([]))]

    chunks: list[tuple[list[dict[str, str]], bool]] = []
    pending: list[dict[str, str]] = []
    for message in normalized_messages:
        pending.append(message)
        if message["role"] == "assistant":
            chunks.append((pending, True))
            pending = []
    if pending:
        chunks.append((pending, False))

    return [
        response_input_item(
            f"{title.removesuffix('_json')}_chunk_{index:04d}_json",
            json_string(chunk),
            cache_breakpoint=cache_breakpoints and is_complete,
        )
        for index, (chunk, is_complete) in enumerate(chunks, start=1)
    ]


def prior_chat_message_objects(
    messages: list[dict[str, Any]],
    latest_user_message: str,
) -> list[dict[str, str]]:
    prior_messages = list(messages)
    if prior_messages:
        last_message = prior_messages[-1]
        if (
            str(last_message.get("role", "")) == "user"
            and str(last_message.get("content", "")) == latest_user_message
        ):
            prior_messages = prior_messages[:-1]
    return chat_message_objects(prior_messages)


def generated_dialogue_object(generated_lesson: dict[str, Any]) -> dict[str, Any]:
    return {
        key: generated_lesson[key]
        for key in ["lesson_id", "dialogue"]
        if key in generated_lesson
    }


def active_comprehension_questions_object(
    generated_lesson: dict[str, Any],
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    questions = generated_lesson.get("comprehension_questions") or []
    if not isinstance(questions, list) or not questions:
        return []

    if state.get("phase") in {"discussion", "translation", "completed"}:
        return []

    current_question_id = state.get("current_question_id")
    if current_question_id is not None:
        for question in questions:
            if isinstance(question, dict) and question.get("id") == current_question_id:
                return [question]

    return questions[:1]


def contains_discussion_stage_invitation(text: str) -> bool:
    normalized = text.lower()
    return any(pattern in normalized for pattern in DISCUSSION_STAGE_TEXT_PATTERNS)


def active_translation_sentence_object(state: dict[str, Any]) -> dict[str, Any] | None:
    quiz = state.get("translation_quiz")
    if not isinstance(quiz, dict):
        return None

    sentences = quiz.get("sentences_en") or []
    if not isinstance(sentences, list) or not sentences:
        return None

    try:
        index = int(state.get("current_translation_index") or 0)
    except (TypeError, ValueError):
        index = 0

    index = min(max(index, 0), len(sentences) - 1)
    return {
        "index": index,
        "sentence_number": index + 1,
        "sentence_count": len(sentences),
        "sentence_en": sentences[index],
    }


def interactor_lesson_state_object(state: dict[str, Any]) -> dict[str, Any]:
    visible_state = {
        key: state[key]
        for key in [
            "lesson_id",
            "phase",
            "current_question_id",
            "translation_quiz",
            "current_translation_index",
            "translation_attempts",
            "mistake_notes",
            "is_completed",
        ]
        if key in state
    }
    active_translation_sentence = active_translation_sentence_object(state)
    quiz = state.get("translation_quiz")

    if active_translation_sentence is not None and isinstance(quiz, dict):
        visible_quiz = dict(quiz)
        visible_quiz["sentences_en"] = [active_translation_sentence["sentence_en"]]
        visible_state["translation_quiz"] = visible_quiz
        visible_state["current_translation_index"] = 0

    return visible_state


def normalize_interactor_markdown(text: str) -> str:
    correction_labels = ("Rättelse:", "Naturligare:")
    rendered_lines: list[str] = []

    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        line_ending = line[len(body) :]
        leading_whitespace = body[: len(body) - len(body.lstrip())]
        trailing_whitespace = body[len(body.rstrip()) :]
        content = body.strip()

        for label in correction_labels:
            if content.startswith(f"**{label}") and content.endswith("**"):
                content = content[2:-2].strip()
            elif content.startswith(f"**{label}**"):
                content = label + content[len(f"**{label}**") :]

            if content.startswith(label):
                corrected_sentence = content[len(label) :].strip()
                if corrected_sentence.startswith("**") and corrected_sentence.endswith("**"):
                    corrected_sentence = corrected_sentence[2:-2].strip()
                if corrected_sentence:
                    body = (
                        f"{leading_whitespace}{label} **{corrected_sentence}**"
                        f"{trailing_whitespace}"
                    )
                else:
                    body = f"{leading_whitespace}{label}{trailing_whitespace}"
                break
        else:
            if content.startswith("**Förståelse:") and content.endswith("**"):
                assessment = content[2:-2].removeprefix("Förståelse:").strip()
                body = (
                    f"{leading_whitespace}Förståelse: {assessment}"
                    f"{trailing_whitespace}"
                )
            elif content.startswith("**Förståelse:**"):
                body = (
                    f"{leading_whitespace}Förståelse:"
                    f"{content[len('**Förståelse:**') :]}{trailing_whitespace}"
                )
            else:
                explanation = content
                if explanation.startswith("**Kort förklaring:") and explanation.endswith("**"):
                    explanation = explanation[2:-2].strip()
                elif explanation.startswith("**Kort förklaring:**"):
                    explanation = explanation[len("**Kort förklaring:**") :].strip()
                if explanation.startswith("Kort förklaring:"):
                    explanation = explanation[len("Kort förklaring:") :].strip()
                if explanation != content:
                    body = f"{leading_whitespace}{explanation}{trailing_whitespace}"

        rendered_lines.append(body + line_ending)

    return "".join(rendered_lines)


def sanitized_interactor_response(response: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(response)
    assistant_text = sanitized.get("assistant_text")
    if isinstance(assistant_text, str):
        sanitized["assistant_text"] = normalize_interactor_markdown(assistant_text)
    state_patch = dict(sanitized.get("state_patch") or {})
    state_patch["phase"] = None
    state_patch["current_question_id"] = None
    if not isinstance(state_patch.get("mistake_notes_add"), list):
        state_patch["mistake_notes_add"] = []
    sanitized["state_patch"] = state_patch
    return sanitized


def response_input_item(
    title: str,
    content: str,
    *,
    role: str = "user",
    cache_breakpoint: bool = False,
) -> dict[str, Any]:
    text = f"{title}:\n{content}"
    if not cache_breakpoint:
        return {"role": role, "content": text}
    return {
        "type": "message",
        "role": role,
        "content": [
            {
                "type": "input_text",
                "text": text,
                "prompt_cache_breakpoint": {"mode": "explicit"},
            }
        ],
    }


def _input_item_text(item: dict[str, Any]) -> str:
    content = item.get("content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    return "".join(
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "input_text"
    )


def _uses_gpt56_prompt_caching(model: str) -> bool:
    return model.strip().lower().startswith("gpt-5.6")


def _prompt_cache_retention_for_model(model: str) -> str | None:
    normalized = model.lower()
    if _uses_gpt56_prompt_caching(normalized):
        return None
    if normalized.startswith("gpt-5") or normalized.startswith("gpt-4.1"):
        return "24h"
    return None


def _input_section_metrics(
    input_value: Any,
    *,
    instructions: str | None = None,
    schema: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    prompt_seed: dict[str, Any] = {
        "instructions": instructions or "",
        "schema": schema or {},
    }
    if isinstance(input_value, list):
        sections: list[dict[str, Any]] = []
        prefix_items: list[Any] = []
        for item in input_value:
            if not isinstance(item, dict):
                prefix_items.append(item)
                sections.append(
                    {
                        "type": type(item).__name__,
                        "item_sha256": json_sha256(item),
                        "prompt_prefix_sha256": json_sha256({**prompt_seed, "input": prefix_items}),
                    }
                )
                continue
            content = _input_item_text(item)
            title = content.split(":\n", 1)[0] if ":\n" in content else None
            prefix_items.append(item)
            sections.append(
                {
                    "role": item.get("role"),
                    "title": title,
                    "chars": len(content),
                    "content_sha256": short_sha256(content),
                    "item_sha256": json_sha256(item),
                    "prompt_prefix_sha256": json_sha256({**prompt_seed, "input": prefix_items}),
                }
            )
        return sections
    if isinstance(input_value, str):
        return [
            {
                "type": "string",
                "chars": len(input_value),
                "content_sha256": short_sha256(input_value),
                "prompt_prefix_sha256": json_sha256({**prompt_seed, "input": input_value}),
            }
        ]
    return [
        {
            "type": type(input_value).__name__,
            "item_sha256": json_sha256(input_value),
            "prompt_prefix_sha256": json_sha256({**prompt_seed, "input": input_value}),
        }
    ]


def _usage_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _usage_metric(usage: dict[str, Any], key: str) -> int | None:
    return _usage_int(usage.get(key))


def _cached_tokens_from_usage(usage: dict[str, Any]) -> int | None:
    for details_key in ["input_tokens_details", "prompt_tokens_details"]:
        details = usage.get(details_key)
        if isinstance(details, dict):
            cached = _usage_int(details.get("cached_tokens"))
            if cached is not None:
                return cached
    return None


def _cache_write_tokens_from_usage(usage: dict[str, Any]) -> int | None:
    for details_key in ["input_tokens_details", "prompt_tokens_details"]:
        details = usage.get(details_key)
        if isinstance(details, dict):
            cache_write = _usage_int(details.get("cache_write_tokens"))
            if cache_write is not None:
                return cache_write
    return None


def _reasoning_tokens_from_usage(usage: dict[str, Any]) -> int | None:
    for details_key in ["output_tokens_details", "completion_tokens_details"]:
        details = usage.get(details_key)
        if isinstance(details, dict):
            reasoning = _usage_int(details.get("reasoning_tokens"))
            if reasoning is not None:
                return reasoning
    return None


def _estimated_cost_metrics(
    settings: Settings,
    model: str,
    usage: dict[str, Any],
) -> dict[str, float | None]:
    empty = {
        "estimated_cost_usd": None,
        "effective_input_cost_usd": None,
        "uncached_input_cost_usd": None,
        "net_cache_savings_usd": None,
        "net_cache_savings_ratio": None,
    }
    prices = settings.openai_usage_price_overrides or {}
    model_prices = prices.get(model)
    if not isinstance(model_prices, dict):
        return empty

    input_price = model_prices.get("input_per_million")
    output_price = model_prices.get("output_per_million")
    cached_input_price = model_prices.get("cached_input_per_million", input_price)
    if input_price is None or output_price is None:
        return empty

    cache_write_price = model_prices.get("cache_write_per_million")
    if cache_write_price is None:
        cache_write_price = float(input_price) * (1.25 if _uses_gpt56_prompt_caching(model) else 1.0)

    input_tokens = _usage_metric(usage, "input_tokens") or _usage_metric(usage, "prompt_tokens") or 0
    output_tokens = _usage_metric(usage, "output_tokens") or _usage_metric(usage, "completion_tokens") or 0
    cached_tokens = _cached_tokens_from_usage(usage) or 0
    cache_write_tokens = _cache_write_tokens_from_usage(usage) or 0
    ordinary_input_tokens = max(input_tokens - cached_tokens - cache_write_tokens, 0)
    effective_input_cost = (
        ordinary_input_tokens * float(input_price)
        + cache_write_tokens * float(cache_write_price)
        + cached_tokens * float(cached_input_price)
    ) / 1_000_000
    uncached_input_cost = input_tokens * float(input_price) / 1_000_000
    net_cache_savings = uncached_input_cost - effective_input_cost
    estimated_cost = effective_input_cost + output_tokens * float(output_price) / 1_000_000
    net_cache_savings_ratio = (
        net_cache_savings / uncached_input_cost if uncached_input_cost else None
    )
    return {
        "estimated_cost_usd": round(estimated_cost, 8),
        "effective_input_cost_usd": round(effective_input_cost, 8),
        "uncached_input_cost_usd": round(uncached_input_cost, 8),
        "net_cache_savings_usd": round(net_cache_savings, 8),
        "net_cache_savings_ratio": round(net_cache_savings_ratio, 4)
        if net_cache_savings_ratio is not None
        else None,
    }


def _estimated_cost_usd(settings: Settings, model: str, usage: dict[str, Any]) -> float | None:
    return _estimated_cost_metrics(settings, model, usage)["estimated_cost_usd"]


def _log_openai_usage(
    *,
    settings: Settings,
    user_id: int | None,
    request_role: str,
    request_name: str,
    model: str,
    lesson_id: str | None,
    prompt_cache_key: str | None,
    prompt_cache_retention: str | None,
    prompt_cache_options: dict[str, str] | None,
    prompt_version: str | None,
    instructions: str,
    input_value: Any,
    schema: dict[str, Any],
    payload: dict[str, Any],
    elapsed_ms: int,
    openai_request_id: str | None,
) -> dict[str, Any] | None:
    input_sections = _input_section_metrics(
        input_value,
        instructions=instructions if prompt_cache_options is None else None,
        schema=schema,
    )
    prompt_fingerprints = {
        "instructions_sha256": short_sha256(instructions),
        "schema_sha256": json_sha256(schema),
        "input_sha256": json_sha256(input_value),
    }
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        logger.info(
            "openai_response_usage %s",
            json.dumps(
                {
                    "request": request_name,
                    "model": model,
                    "lesson_id": lesson_id,
                    "source_id": lesson_id,
                    "prompt_cache_key": prompt_cache_key,
                    "prompt_cache_retention": prompt_cache_retention,
                    "prompt_cache_options": prompt_cache_options,
                    "prompt_version": prompt_version,
                    **prompt_fingerprints,
                    "elapsed_ms": elapsed_ms,
                    "openai_request_id": openai_request_id,
                    "usage_present": False,
                    "input_sections": input_sections,
                },
                sort_keys=True,
            ),
        )
        return None

    input_tokens = _usage_metric(usage, "input_tokens") or _usage_metric(usage, "prompt_tokens")
    output_tokens = _usage_metric(usage, "output_tokens") or _usage_metric(usage, "completion_tokens")
    cached_tokens = _cached_tokens_from_usage(usage)
    cache_write_tokens = _cache_write_tokens_from_usage(usage)
    ordinary_input_tokens = (
        max(input_tokens - (cached_tokens or 0) - (cache_write_tokens or 0), 0)
        if input_tokens is not None
        else None
    )
    total_tokens = _usage_metric(usage, "total_tokens")
    reasoning_tokens = _reasoning_tokens_from_usage(usage)
    cache_read_ratio = round((cached_tokens or 0) / input_tokens, 4) if input_tokens else None
    cache_write_ratio = round((cache_write_tokens or 0) / input_tokens, 4) if input_tokens else None
    cost_metrics = _estimated_cost_metrics(settings, model, usage)
    logger.info(
        "openai_response_usage %s",
        json.dumps(
            {
                "request": request_name,
                "model": model,
                "lesson_id": lesson_id,
                "source_id": lesson_id,
                "prompt_cache_key": prompt_cache_key,
                "prompt_cache_retention": prompt_cache_retention,
                "prompt_cache_options": prompt_cache_options,
                "prompt_version": prompt_version,
                **prompt_fingerprints,
                "elapsed_ms": elapsed_ms,
                "openai_request_id": openai_request_id,
                "usage_present": True,
                "input_tokens": input_tokens,
                "cached_tokens": cached_tokens,
                "cache_write_tokens": cache_write_tokens,
                "ordinary_input_tokens": ordinary_input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": reasoning_tokens,
                "total_tokens": total_tokens,
                "cache_ratio": cache_read_ratio,
                "cache_read_ratio": cache_read_ratio,
                "cache_write_ratio": cache_write_ratio,
                **cost_metrics,
                "input_sections": input_sections,
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
        "source_id": lesson_id,
        "model": model,
        "prompt_version": prompt_version,
        "prompt_cache_key": prompt_cache_key,
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "cache_write_tokens": cache_write_tokens,
        "ordinary_input_tokens": ordinary_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
        **cost_metrics,
        "actual_cost_usd": None,
        "elapsed_ms": elapsed_ms,
        "openai_request_id": openai_request_id,
        "created_at": datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "raw_usage": usage,
    }


def generator_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "generated_lesson",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["lesson_id", "dialogue", "comprehension_questions"],
            "properties": {
                "lesson_id": {"type": "string"},
                "dialogue": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["speaker", "text"],
                        "properties": {
                            "speaker": {"type": "string", "enum": ["Anna", "Erik"]},
                            "text": {"type": "string"},
                        },
                    },
                },
                "comprehension_questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "question_sv"],
                        "properties": {
                            "id": {"type": "string"},
                            "question_sv": {"type": "string"},
                        },
                    },
                },
            },
        },
    }


def interactor_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "lesson_interaction",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["assistant_text", "state_patch", "translation_quiz"],
            "properties": {
                "assistant_text": {"type": "string"},
                "state_patch": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "phase",
                        "current_question_id",
                        "mistake_notes_add",
                    ],
                    "properties": {
                        "phase": {
                            "anyOf": [
                                {"type": "string", "enum": INTERACTOR_PATCHABLE_PHASES},
                                {"type": "null"},
                            ]
                        },
                        "current_question_id": {
                            "anyOf": [
                                {"type": "string"},
                                {"type": "null"},
                            ]
                        },
                        "mistake_notes_add": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["category", "note"],
                                "properties": {
                                    "category": {"type": "string"},
                                    "note": {"type": "string"},
                                },
                            },
                        },
                    },
                },
                "translation_quiz": {
                    "anyOf": [
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["sentences_en"],
                            "properties": {
                                "sentences_en": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                }
                            },
                        },
                        {"type": "null"},
                    ]
                },
            },
        },
    }


def vocabulary_quiz_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "vocabulary_quiz",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["questions", "opening_text"],
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": 5,
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "sentence_en", "target_keys"],
                        "properties": {
                            "id": {"type": "string"},
                            "sentence_en": {"type": "string"},
                            "target_keys": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"type": "string"},
                            },
                        },
                    },
                },
                "opening_text": {"type": "string"},
            },
        },
    }


def vocabulary_interaction_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "vocabulary_interaction",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["assistant_text", "turn_kind", "answer_assessment", "active_question_answered"],
            "properties": {
                "assistant_text": {"type": "string"},
                "turn_kind": {"type": "string", "enum": ["answer_feedback", "free_form_chat"]},
                "answer_assessment": {
                    "type": "string",
                    "enum": ["correct", "partial", "incorrect", "not_an_answer"],
                },
                "active_question_answered": {"type": "boolean"},
            },
        },
    }


def evaluator_candidate_projection(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "target_key": candidate.get("target_key"),
            "target_kind": candidate.get("target_kind"),
            "display_text": candidate.get("display_text"),
            "description": candidate.get("description"),
        }
        for candidate in snapshot.get("candidates", [])
        if isinstance(candidate, dict) and candidate.get("target_key")
    ]


def evaluator_user_state_projection(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    current_state = snapshot.get("current_user_state") or {}
    if not isinstance(current_state, dict):
        return {}
    return {
        str(key): {
            "status": value.get("status"),
            "success_streak": value.get("success_streak"),
        }
        for key, value in current_state.items()
        if isinstance(value, dict)
    }


def evaluator_schema(
    *,
    evaluation_version: str = "v3",
    source_kind: str = "lesson",
) -> dict[str, Any]:
    if evaluation_version in {"v1", "v2"}:
        return _legacy_evaluator_schema()
    if evaluation_version != "v3":
        raise ValueError(f"Unsupported evaluator schema version: {evaluation_version}")

    is_lookup = source_kind == "translation_lookup"
    evidence_ids_key = "evidence_lookup_ids" if is_lookup else "evidence_turn_ids"
    update_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "target_key",
            "outcome",
            "evidence_strength",
            "confidence",
            evidence_ids_key,
            "reason",
        ],
        "properties": {
            "target_key": {"type": "string"},
            "outcome": {
                "type": "string",
                "enum": ["lookup_requested"] if is_lookup else ["struggled", "partial", "demonstrated"],
            },
            "evidence_strength": {
                "type": "string",
                "enum": ["lookup"] if is_lookup else ["production", "recognition", "assisted_production"],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            evidence_ids_key: {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},
            },
            "reason": {"type": "string"},
        },
    }
    return {
        "type": "json_schema",
        "name": "learning_evaluation",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["evaluation_version", "checked_target_keys", "updates"],
            "properties": {
                "evaluation_version": {"type": "string", "enum": ["v3"]},
                "checked_target_keys": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string"},
                },
                "updates": {"type": "array", "items": update_schema},
            },
        },
    }


def _legacy_evaluator_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "learning_evaluation",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["evaluation_version", "results"],
            "properties": {
                "evaluation_version": {"type": "string", "enum": ["v1", "v2"]},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "target_kind",
                            "target_key",
                            "outcome",
                            "evidence_strength",
                            "confidence",
                            "evidence_turn_ids",
                            "evidence_lookup_ids",
                            "reason",
                        ],
                        "properties": {
                            "target_kind": {"type": "string", "enum": ["vocabulary", "grammar"]},
                            "target_key": {"type": "string"},
                            "outcome": {
                                "type": "string",
                                "enum": ["struggled", "partial", "demonstrated", "no_evidence", "lookup_requested"],
                            },
                            "evidence_strength": {
                                "type": "string",
                                "enum": ["production", "recognition", "assisted_production", "lookup"],
                            },
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "evidence_turn_ids": {"type": "array", "items": {"type": "string"}},
                            "evidence_lookup_ids": {"type": "array", "items": {"type": "string"}},
                            "reason": {"type": "string"},
                        },
                    },
                },
            },
        },
    }


async def send_structured_request(
    settings: Settings,
    *,
    request_role: str,
    user_id: int | None = None,
    request_name: str,
    lesson_id: str | None,
    model: str,
    reasoning_effort: str,
    instructions: str,
    input_value: Any,
    schema: dict[str, Any],
    max_output_tokens: int,
    prompt_cache_key: str | None = None,
    prompt_version: str | None = None,
    usage_recorder: UsageRecorder | None = None,
    response_metadata_recorder: ResponseMetadataRecorder | None = None,
) -> dict[str, Any]:
    uses_explicit_cache = bool(prompt_cache_key and _uses_gpt56_prompt_caching(model))
    request_input = input_value
    if uses_explicit_cache:
        developer_item = response_input_item(
            "developer_instructions",
            instructions,
            role="developer",
            cache_breakpoint=True,
        )
        if isinstance(input_value, list):
            request_input = [developer_item, *input_value]
        else:
            request_input = [developer_item, {"role": "user", "content": str(input_value)}]

    body: dict[str, Any] = {
        "model": model,
        "input": request_input,
        "max_output_tokens": max_output_tokens,
        "reasoning": {"effort": reasoning_effort},
        "text": {"format": schema},
    }
    if not uses_explicit_cache:
        body["instructions"] = instructions
    if prompt_cache_key:
        body["prompt_cache_key"] = prompt_cache_key
    prompt_cache_retention = _prompt_cache_retention_for_model(model)
    prompt_cache_options = None
    if prompt_cache_retention:
        body["prompt_cache_retention"] = prompt_cache_retention
    if uses_explicit_cache:
        prompt_cache_options = {"mode": "explicit", "ttl": GPT56_PROMPT_CACHE_TTL}
        body["prompt_cache_options"] = prompt_cache_options

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=settings.openai_timeout_seconds) as client:
        started = time.perf_counter()
        response = await client.post(OPENAI_RESPONSES_URL, headers=headers, json=body)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    if response.status_code < 200 or response.status_code > 299:
        message = _upstream_error_message(response)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OpenAI error: {message}")

    payload = response.json()
    if response_metadata_recorder is not None:
        response_metadata_recorder(
            {
                "provider_model": str(payload.get("model")) if payload.get("model") else None,
                "provider_request_id": response.headers.get("x-request-id") or (
                    str(payload.get("id")) if payload.get("id") else None
                ),
            }
        )
    usage_event = _log_openai_usage(
        settings=settings,
        user_id=user_id,
        request_role=request_role,
        request_name=request_name,
        model=model,
        lesson_id=lesson_id,
        prompt_cache_key=prompt_cache_key,
        prompt_cache_retention=prompt_cache_retention,
        prompt_cache_options=prompt_cache_options,
        prompt_version=prompt_version,
        instructions=instructions,
        input_value=request_input,
        schema=schema,
        payload=payload,
        elapsed_ms=elapsed_ms,
        openai_request_id=response.headers.get("x-request-id"),
    )
    if usage_event is not None and usage_recorder is not None:
        usage_recorder(usage_event)
    refusal = _refusal_text(payload)
    if refusal:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OpenAI refused request: {refusal}")

    output_text = _best_text(payload).strip()
    if not output_text:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="OpenAI returned no structured output.")

    try:
        decoded = json.loads(output_text)
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OpenAI returned invalid structured JSON.",
        ) from error

    if not isinstance(decoded, dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="OpenAI returned unexpected JSON.")
    return decoded


async def generate_lesson(
    settings: Settings,
    *,
    user_id: int | None = None,
    payload: dict[str, Any],
    model: str,
    reasoning_effort: str,
    usage_recorder: UsageRecorder | None = None,
    response_metadata_recorder: ResponseMetadataRecorder | None = None,
) -> dict[str, Any]:
    shared_base_prompt, generator_prompt = generator_prompt_sources()
    instructions = "\n\n".join([shared_base_prompt, generator_prompt])
    draft = await send_structured_request(
        settings,
        request_role="Generator",
        user_id=user_id,
        request_name="lesson_generator",
        lesson_id=str(payload.get("id", "")),
        model=model,
        reasoning_effort=reasoning_effort,
        instructions=instructions,
        input_value=json_string(snake_case_keys(payload)),
        schema=generator_schema(),
        max_output_tokens=4_000,
        prompt_cache_key=GENERATOR_PROMPT_CACHE_KEY,
        prompt_version="lesson_generator_v1",
        usage_recorder=usage_recorder,
        response_metadata_recorder=response_metadata_recorder,
    )
    validate_generated_lesson_draft(draft, payload)
    return build_generated_lesson(draft, model)


async def send_lesson_message(
    settings: Settings,
    *,
    user_id: int | None = None,
    payload: dict[str, Any],
    generated_lesson: dict[str, Any],
    state: dict[str, Any],
    chat_history: list[dict[str, Any]],
    latest_user_message: str,
    model: str,
    reasoning_effort: str,
    usage_recorder: UsageRecorder | None = None,
) -> dict[str, Any]:
    instructions = "\n\n".join([_read_prompt("Shared_base_prompt"), _read_prompt("Interactor_prompt")])
    lesson_id = str(payload.get("id", ""))
    uses_explicit_cache = _uses_gpt56_prompt_caching(model)
    prior_messages = prior_chat_message_objects(chat_history, latest_user_message)
    input_value = [
        response_input_item("course_context_json", json_string(course_context_object(payload))),
        response_input_item(
            "lesson_payload_json",
            json_string(snake_case_keys(payload)),
            cache_breakpoint=uses_explicit_cache,
        ),
        response_input_item(
            "generated_dialogue_json",
            json_string(generated_dialogue_object(generated_lesson)),
            cache_breakpoint=uses_explicit_cache,
        ),
        *append_only_history_input_items(
            "prior_lesson_chat_history_json",
            prior_messages,
            cache_breakpoints=uses_explicit_cache,
        ),
        response_input_item(
            "active_comprehension_questions_json",
            json_string(active_comprehension_questions_object(generated_lesson, state)),
        ),
        response_input_item("active_translation_sentence_json", json_string(active_translation_sentence_object(state))),
        response_input_item("lesson_state_json", json_string(interactor_lesson_state_object(state))),
        response_input_item("latest_user_message", latest_user_message),
    ]
    response = await send_structured_request(
        settings,
        request_role="Interactor",
        user_id=user_id,
        request_name="lesson_interactor",
        lesson_id=lesson_id,
        model=model,
        reasoning_effort=reasoning_effort,
        instructions=instructions,
        input_value=input_value,
        schema=interactor_schema(),
        max_output_tokens=2_000,
        prompt_cache_key=scoped_prompt_cache_key(INTERACTOR_PROMPT_CACHE_KEY, lesson_id),
        prompt_version="lesson_interactor_v1",
        usage_recorder=usage_recorder,
    )
    try:
        response = sanitized_interactor_response(response)
        validate_interactor_response(response, generated_lesson, state, latest_user_message)
    except ValueError as first_error:
        retry_input_value = [
            *input_value,
            response_input_item("previous_invalid_interactor_response_json", json_string(response)),
            response_input_item("validation_error", str(first_error)),
            response_input_item(
                "retry_instruction",
                (
                    "Return corrected JSON only. Keep the learner in the current app-owned lesson phase. "
                    "During comprehension, evaluate only the active question, do not advance to discussion, "
                    "and do not invite the learner to reread the dialogue until the app enters discussion. "
                    "Keep phase and current_question_id null, and generate translation_quiz only for the "
                    "start_translation_quiz system UI action."
                ),
            ),
        ]
        response = await send_structured_request(
            settings,
            request_role="Interactor",
            user_id=user_id,
            request_name="lesson_interactor_retry",
            lesson_id=lesson_id,
            model=model,
            reasoning_effort=reasoning_effort,
            instructions=instructions,
            input_value=retry_input_value,
            schema=interactor_schema(),
            max_output_tokens=2_000,
            prompt_cache_key=scoped_prompt_cache_key(INTERACTOR_PROMPT_CACHE_KEY, lesson_id),
            prompt_version="lesson_interactor_v1",
            usage_recorder=usage_recorder,
        )
        try:
            response = sanitized_interactor_response(response)
            validate_interactor_response(response, generated_lesson, state, latest_user_message)
        except ValueError as second_error:
            raise ValueError(f"Interactor returned invalid response after retry: {second_error}") from second_error
    return response


async def generate_vocabulary_quiz(
    settings: Settings,
    *,
    user_id: int | None = None,
    practice_id: str,
    progression: dict[str, Any],
    selected_targets: list[dict[str, Any]],
    model: str,
    reasoning_effort: str,
    usage_recorder: UsageRecorder | None = None,
) -> dict[str, Any]:
    instructions = "\n\n".join(
        [_read_prompt("Shared_base_prompt"), _read_prompt("Vocabulary_interactor_prompt")]
    )
    input_value = [
        response_input_item(
            "course_and_progression_context_json",
            json_string(
                {
                    **progression,
                    "explanation_swedish_level": "B1" if progression.get("course_level") == "B2" else "A2",
                }
            ),
        ),
        response_input_item("selected_target_definitions_json", json_string(selected_targets)),
        response_input_item("generation_action", "Generate the five-question vocabulary practice now."),
    ]
    return await send_structured_request(
        settings,
        request_role="Vocabulary Quiz",
        user_id=user_id,
        request_name="vocabulary_quiz_generator",
        lesson_id=practice_id,
        model=model,
        reasoning_effort=reasoning_effort,
        instructions=instructions,
        input_value=input_value,
        schema=vocabulary_quiz_schema(),
        max_output_tokens=2_000,
        prompt_cache_key=VOCABULARY_QUIZ_PROMPT_CACHE_KEY,
        prompt_version="vocabulary_interactor_v1",
        usage_recorder=usage_recorder,
    )


async def send_vocabulary_message(
    settings: Settings,
    *,
    user_id: int | None = None,
    practice_id: str,
    context: dict[str, Any],
    latest_user_message: str,
    model: str,
    reasoning_effort: str,
    usage_recorder: UsageRecorder | None = None,
) -> dict[str, Any]:
    instructions = "\n\n".join(
        [_read_prompt("Shared_base_prompt"), _read_prompt("Vocabulary_interactor_prompt")]
    )
    uses_explicit_cache = _uses_gpt56_prompt_caching(model)
    progression = dict(context["progression"])
    progression["explanation_swedish_level"] = "B1" if progression.get("course_level") == "B2" else "A2"
    input_value = [
        response_input_item("course_and_progression_context_json", json_string(progression)),
        response_input_item("selected_target_definitions_json", json_string(context["selected_targets"])),
        response_input_item(
            "full_quiz_metadata_json",
            json_string(context["quiz"]),
            cache_breakpoint=uses_explicit_cache,
        ),
        *append_only_history_input_items(
            "prior_practice_chat_history_json",
            context["prior_messages"],
            cache_breakpoints=uses_explicit_cache,
        ),
        response_input_item("active_question_json", json_string(context["active_question"])),
        response_input_item("practice_state_json", json_string(context["practice_state"])),
        response_input_item("latest_user_message", latest_user_message),
    ]
    return await send_structured_request(
        settings,
        request_role="Vocabulary Interactor",
        user_id=user_id,
        request_name="vocabulary_interactor",
        lesson_id=practice_id,
        model=model,
        reasoning_effort=reasoning_effort,
        instructions=instructions,
        input_value=input_value,
        schema=vocabulary_interaction_schema(),
        max_output_tokens=1_500,
        prompt_cache_key=scoped_prompt_cache_key(VOCABULARY_INTERACTOR_PROMPT_CACHE_KEY, practice_id),
        prompt_version="vocabulary_interactor_v1",
        usage_recorder=usage_recorder,
    )


async def evaluate_learning_snapshot(
    settings: Settings,
    *,
    user_id: int | None = None,
    source_id: str,
    snapshot: dict[str, Any],
    model: str,
    reasoning_effort: str,
    usage_recorder: UsageRecorder | None = None,
) -> dict[str, Any]:
    instructions = "\n\n".join([_read_prompt("Shared_base_prompt"), _read_prompt("Evaluator_prompt")])
    evaluation_version = str(snapshot.get("evaluation_version") or "v1")
    source_kind = str(snapshot.get("source_kind") or "")
    input_value = [
        response_input_item(
            "evaluation_metadata_json",
            json_string(
                {
                    "evaluation_version": evaluation_version,
                    "source_kind": source_kind,
                    "source_id": snapshot.get("source_id"),
                }
            ),
        ),
        response_input_item("candidate_target_catalog_json", json_string(evaluator_candidate_projection(snapshot))),
        response_input_item("current_user_state_json", json_string(evaluator_user_state_projection(snapshot))),
        response_input_item(
            "source_context_json",
            json_string(
                {
                    **(snapshot.get("source_context") or {}),
                    "progression": snapshot.get("progression"),
                }
            ),
        ),
        response_input_item("session_quiz_json", json_string(snapshot.get("quiz"))),
        response_input_item("lookup_events_json", json_string(snapshot.get("lookup_events") or [])),
        response_input_item("turn_numbered_evidence_json", json_string(snapshot.get("turns") or [])),
    ]
    return await send_structured_request(
        settings,
        request_role="Evaluator",
        user_id=user_id,
        request_name="learning_evaluator",
        lesson_id=source_id,
        model=model,
        reasoning_effort=reasoning_effort,
        instructions=instructions,
        input_value=input_value,
        schema=evaluator_schema(evaluation_version=evaluation_version, source_kind=source_kind),
        max_output_tokens=4_000,
        prompt_cache_key=EVALUATOR_PROMPT_CACHE_KEY,
        prompt_version="evaluator_v3",
        usage_recorder=usage_recorder,
    )


def validate_generated_lesson_draft(draft: dict[str, Any], payload: dict[str, Any]) -> None:
    expected_id = payload.get("id")
    if draft.get("lesson_id") != expected_id:
        raise ValueError(f"Generated lesson ID {draft.get('lesson_id')} does not match payload ID {expected_id}.")

    dialogue = draft.get("dialogue") or []
    if len(dialogue) != 20:
        raise ValueError(f"Generated dialogue has {len(dialogue)} lines. It must have exactly 20 lines.")
    for index, line in enumerate(dialogue):
        text = str((line or {}).get("text", "")).strip()
        if not text:
            raise ValueError(f"Generated dialogue line {index + 1} is empty.")
        if text.startswith(("(", "[", "*")):
            raise ValueError(f"Generated dialogue line {index + 1} appears to contain a stage direction.")

    questions = draft.get("comprehension_questions") or []
    if len(questions) != 3:
        raise ValueError(f"Generated lesson has {len(questions)} comprehension questions. It must have exactly 3.")
    ids = [question.get("id") for question in questions]
    if len(set(ids)) != len(ids):
        raise ValueError("Generated comprehension question IDs must be unique.")
    disallowed = ["vad sa anna", "vad sa erik", "what did anna", "what did erik", "vem sa"]
    for question in questions:
        text = str(question.get("question_sv", "")).lower()
        if any(pattern in text for pattern in disallowed):
            raise ValueError("Comprehension questions must not ask what Anna or Erik said.")


def validate_interactor_response(
    response: dict[str, Any],
    generated_lesson: dict[str, Any],
    state: dict[str, Any],
    latest_user_message: str,
) -> None:
    if not str(response.get("assistant_text", "")).strip():
        raise ValueError("Interactor returned an empty assistant response.")

    state_patch = response.get("state_patch") or {}
    phase = state_patch.get("phase")
    if phase is not None and phase not in INTERACTOR_PATCHABLE_PHASES:
        raise ValueError(f"Interactor cannot set lesson phase to {phase}.")

    state_phase = state.get("phase")
    is_before_discussion = state_phase in PRE_DISCUSSION_PHASES

    if is_before_discussion and phase in {"discussion", "translation"}:
        raise ValueError(f"Interactor cannot advance lesson phase from {state_phase} to {phase}.")

    if is_before_discussion and contains_discussion_stage_invitation(str(response.get("assistant_text", ""))):
        raise ValueError("Interactor returned discussion-stage guidance before the discussion phase.")

    quiz = response.get("translation_quiz")
    if quiz is not None and len(quiz.get("sentences_en") or []) != 5:
        raise ValueError("Translation quiz must have exactly 5 sentences.")
    if quiz is not None:
        if latest_user_message != START_TRANSLATION_QUIZ_COMMAND:
            raise ValueError("Translation quiz can only be generated by the start-quiz UI command.")
        if state_phase != "discussion":
            raise ValueError("Translation quiz can only be generated from the discussion phase.")
    elif phase == "translation" and state_phase != "translation":
        raise ValueError("Interactor cannot enter translation without a translation quiz.")


def build_generated_lesson(draft: dict[str, Any], model: str) -> dict[str, Any]:
    generated = dict(draft)
    generated["generated_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    generated["model"] = model
    generated["schema_version"] = 1
    return generated


def _best_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text:
        return output_text

    chunks: list[str] = []
    for item in payload.get("output") or []:
        for content in item.get("content") or []:
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks)


def _refusal_text(payload: dict[str, Any]) -> str:
    refusals: list[str] = []
    for item in payload.get("output") or []:
        for content in item.get("content") or []:
            refusal = content.get("refusal")
            if isinstance(refusal, str):
                refusals.append(refusal)
    return "\n".join(refusals)


def _upstream_error_message(response: httpx.Response) -> str:
    try:
        decoded = response.json()
        message = decoded.get("error", {}).get("message")
        if isinstance(message, str):
            return message
    except ValueError:
        pass
    return response.text[:500] or f"HTTP {response.status_code}"
