from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import HTTPException, status

from .config import REPO_ROOT, Settings


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
PROMPTS_DIR = REPO_ROOT / "Materials"
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


def generated_dialogue_object(generated_lesson: dict[str, Any]) -> dict[str, Any]:
    return {
        key: generated_lesson[key]
        for key in ["lesson_id", "dialogue", "generated_at", "model", "schema_version"]
        if key in generated_lesson
    }


def active_comprehension_questions_object(
    generated_lesson: dict[str, Any],
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    questions = generated_lesson.get("comprehension_questions") or []
    if not isinstance(questions, list) or not questions:
        return []

    accepted_question_ids = set(state.get("accepted_question_ids") or [])
    question_ids = {question.get("id") for question in questions if isinstance(question, dict)}
    if question_ids and question_ids.issubset(accepted_question_ids):
        return questions

    current_question_id = state.get("current_question_id")
    if current_question_id is not None:
        for question in questions:
            if isinstance(question, dict) and question.get("id") == current_question_id:
                return [question]

    for question in questions:
        if isinstance(question, dict) and question.get("id") not in accepted_question_ids:
            return [question]

    return questions[:1]


def active_comprehension_question_id(
    generated_lesson: dict[str, Any],
    state: dict[str, Any],
) -> str | None:
    active_questions = active_comprehension_questions_object(generated_lesson, state)
    if len(active_questions) != 1:
        return None
    question = active_questions[0]
    if not isinstance(question, dict):
        return None
    question_id = question.get("id")
    return question_id if isinstance(question_id, str) else None


def all_comprehension_questions_accepted(generated_lesson: dict[str, Any], state: dict[str, Any]) -> bool:
    questions = generated_lesson.get("comprehension_questions") or []
    question_ids = {question.get("id") for question in questions if isinstance(question, dict)}
    accepted_question_ids = set(state.get("accepted_question_ids") or [])
    return bool(question_ids) and question_ids.issubset(accepted_question_ids)


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
    visible_state = dict(state)
    active_translation_sentence = active_translation_sentence_object(state)
    quiz = state.get("translation_quiz")

    if active_translation_sentence is not None and isinstance(quiz, dict):
        visible_quiz = dict(quiz)
        visible_quiz["sentences_en"] = [active_translation_sentence["sentence_en"]]
        visible_state["translation_quiz"] = visible_quiz
        visible_state["current_translation_index"] = 0

    return visible_state


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
        response_input_item("generated_dialogue_json", json_string(generated_dialogue_object(generated_lesson))),
        response_input_item(
            "active_comprehension_questions_json",
            json_string(active_comprehension_questions_object(generated_lesson, state)),
        ),
        response_input_item("active_translation_sentence_json", json_string(active_translation_sentence_object(state))),
        response_input_item("full_lesson_chat_history_json", json_string(chat_message_objects(chat_history))),
        response_input_item("lesson_state_json", json_string(interactor_lesson_state_object(state))),
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
    try:
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
                    "Generate translation_quiz only for the start_translation_quiz system UI action."
                ),
            ),
        ]
        response = await send_structured_request(
            settings,
            model=model,
            reasoning_effort=reasoning_effort,
            instructions=instructions,
            input_value=retry_input_value,
            schema=interactor_schema(),
            max_output_tokens=2_000,
            prompt_cache_key=f"lesson_interactor_{payload.get('id', 'unknown')}",
        )
        try:
            validate_interactor_response(response, generated_lesson, state, latest_user_message)
        except ValueError as second_error:
            raise ValueError(f"Interactor returned invalid response after retry: {second_error}") from second_error
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

    questions = generated_lesson.get("comprehension_questions") or []
    valid_question_ids = {question.get("id") for question in questions if isinstance(question, dict)}
    accepted_question_ids = set(state.get("accepted_question_ids") or [])
    active_question_id = active_comprehension_question_id(generated_lesson, state)
    state_phase = state.get("phase")
    is_before_discussion = state_phase in PRE_DISCUSSION_PHASES

    if is_before_discussion and phase in {"discussion", "translation"}:
        raise ValueError(f"Interactor cannot advance lesson phase from {state_phase} to {phase}.")

    if is_before_discussion and contains_discussion_stage_invitation(str(response.get("assistant_text", ""))):
        raise ValueError("Interactor returned discussion-stage guidance before the discussion phase.")

    current_question_id = state_patch.get("current_question_id")
    if current_question_id is not None and current_question_id not in valid_question_ids:
        raise ValueError(f"Interactor referenced an unknown question ID: {current_question_id}.")

    if (
        is_before_discussion
        and active_question_id is not None
        and current_question_id is not None
        and current_question_id != active_question_id
    ):
        raise ValueError(
            f"Interactor cannot move current question from {active_question_id} to {current_question_id}."
        )

    accepted_question_ids_add = state_patch.get("accepted_question_ids_add") or []
    if not isinstance(accepted_question_ids_add, list):
        raise ValueError("accepted_question_ids_add must be an array.")

    for question_id in accepted_question_ids_add:
        if question_id not in valid_question_ids:
            raise ValueError(f"Interactor referenced an unknown question ID: {question_id}.")

    if accepted_question_ids_add:
        if len(accepted_question_ids_add) != 1:
            raise ValueError("Interactor can accept only the active comprehension question in one turn.")
        question_id = accepted_question_ids_add[0]
        if active_question_id is None or question_id != active_question_id:
            raise ValueError(
                f"Interactor can accept only the active comprehension question ID: {active_question_id}."
            )

    quiz = response.get("translation_quiz")
    if quiz is not None and len(quiz.get("sentences_en") or []) != 5:
        raise ValueError("Translation quiz must have exactly 5 sentences.")
    if quiz is not None:
        if latest_user_message != START_TRANSLATION_QUIZ_COMMAND:
            raise ValueError("Translation quiz can only be generated by the start-quiz UI command.")
        if state_phase != "discussion":
            raise ValueError("Translation quiz can only be generated from the discussion phase.")
        if not all_comprehension_questions_accepted(generated_lesson, state):
            raise ValueError("Translation quiz requires all comprehension questions to be accepted.")
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
