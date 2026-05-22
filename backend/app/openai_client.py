from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException, status

from .config import REPO_ROOT, Settings


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
PROMPTS_DIR = REPO_ROOT / "SWE_Dialogs" / "SWE_Dialogs" / "Resources" / "TutorPrompts"
INTERACTOR_PATCHABLE_PHASES = ["generated", "listening", "comprehension", "discussion", "translation"]


def _read_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


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


def response_input_item(title: str, content: str) -> dict[str, str]:
    return {
        "role": "user",
        "content": f"{title}:\n{content}",
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
                        "accepted_question_ids_add",
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
                        "accepted_question_ids_add": {
                            "type": "array",
                            "items": {"type": "string"},
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


async def send_structured_request(
    settings: Settings,
    *,
    model: str,
    reasoning_effort: str,
    instructions: str,
    input_value: Any,
    schema: dict[str, Any],
    max_output_tokens: int,
    prompt_cache_key: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "instructions": instructions,
        "input": input_value,
        "max_output_tokens": max_output_tokens,
        "reasoning": {"effort": reasoning_effort},
        "text": {"format": schema},
    }
    if prompt_cache_key:
        body["prompt_cache_key"] = prompt_cache_key

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=settings.openai_timeout_seconds) as client:
        response = await client.post(OPENAI_RESPONSES_URL, headers=headers, json=body)

    if response.status_code < 200 or response.status_code > 299:
        message = _upstream_error_message(response)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OpenAI error: {message}")

    payload = response.json()
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
    payload: dict[str, Any],
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    instructions = "\n\n".join([_read_prompt("Shared_base_prompt"), _read_prompt("Generator_prompt")])
    draft = await send_structured_request(
        settings,
        model=model,
        reasoning_effort=reasoning_effort,
        instructions=instructions,
        input_value=json_string(snake_case_keys(payload)),
        schema=generator_schema(),
        max_output_tokens=4_000,
    )
    validate_generated_lesson_draft(draft, payload)
    return build_generated_lesson(draft, model)


async def send_lesson_message(
    settings: Settings,
    *,
    payload: dict[str, Any],
    generated_lesson: dict[str, Any],
    state: dict[str, Any],
    chat_history: list[dict[str, Any]],
    latest_user_message: str,
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    instructions = "\n\n".join([_read_prompt("Shared_base_prompt"), _read_prompt("Interactor_prompt")])
    input_value = [
        response_input_item("course_context_json", json_string(course_context_object(payload))),
        response_input_item("lesson_payload_json", json_string(snake_case_keys(payload))),
        response_input_item("generated_lesson_json", json_string(generated_lesson)),
        response_input_item("full_lesson_chat_history_json", json_string(chat_message_objects(chat_history))),
        response_input_item("lesson_state_json", json_string(state)),
        response_input_item("latest_user_message", latest_user_message),
    ]
    response = await send_structured_request(
        settings,
        model=model,
        reasoning_effort=reasoning_effort,
        instructions=instructions,
        input_value=input_value,
        schema=interactor_schema(),
        max_output_tokens=2_000,
        prompt_cache_key=f"lesson_interactor_{payload.get('id', 'unknown')}",
    )
    validate_interactor_response(response, generated_lesson)
    return response


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


def validate_interactor_response(response: dict[str, Any], generated_lesson: dict[str, Any]) -> None:
    if not str(response.get("assistant_text", "")).strip():
        raise ValueError("Interactor returned an empty assistant response.")

    state_patch = response.get("state_patch") or {}
    phase = state_patch.get("phase")
    if phase is not None and phase not in INTERACTOR_PATCHABLE_PHASES:
        raise ValueError(f"Interactor cannot set lesson phase to {phase}.")

    questions = generated_lesson.get("comprehension_questions") or []
    valid_question_ids = {question.get("id") for question in questions}
    current_question_id = state_patch.get("current_question_id")
    if current_question_id is not None and current_question_id not in valid_question_ids:
        raise ValueError(f"Interactor referenced an unknown question ID: {current_question_id}.")

    for question_id in state_patch.get("accepted_question_ids_add") or []:
        if question_id not in valid_question_ids:
            raise ValueError(f"Interactor referenced an unknown question ID: {question_id}.")

    quiz = response.get("translation_quiz")
    if quiz is not None and len(quiz.get("sentences_en") or []) != 5:
        raise ValueError("Translation quiz must have exactly 5 sentences.")


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
