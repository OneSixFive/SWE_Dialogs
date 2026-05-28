import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from app import openai_client
from app.config import Settings
from app.openai_client import (
    PROMPTS_DIR,
    active_comprehension_questions_object,
    active_translation_sentence_object,
    build_generated_lesson,
    course_context_object,
    generated_dialogue_object,
    interactor_lesson_state_object,
    sanitized_interactor_response,
    snake_case_keys,
    validate_generated_lesson_draft,
    validate_interactor_response,
)


def test_snake_case_keys_converts_nested_payload():
    payload = {
        "coursePosition": {"absoluteDay": 1, "stageName": "Stage"},
        "lessonIntent": {"oneSentenceGoal": "Goal"},
        "activeWords": ["hej"],
    }

    assert snake_case_keys(payload) == {
        "course_position": {"absolute_day": 1, "stage_name": "Stage"},
        "lesson_intent": {"one_sentence_goal": "Goal"},
        "active_words": ["hej"],
    }


def test_course_context_from_lesson_id():
    assert course_context_object({"id": "b1_s1_w1_d1"}) == {
        "course_level": "B1",
        "explanation_swedish_level": "A2",
    }
    assert course_context_object({"id": "b2_s1_w1_d1"}) == {
        "course_level": "B2",
        "explanation_swedish_level": "B1",
    }


def test_backend_reads_prompts_from_materials():
    assert PROMPTS_DIR.name == "Materials"
    assert (PROMPTS_DIR / "Interactor_prompt.md").is_file()
    assert (PROMPTS_DIR / "Generator_prompt.md").is_file()
    assert (PROMPTS_DIR / "Shared_base_prompt.md").is_file()


def test_build_generated_lesson_adds_app_fields():
    draft = {
        "lesson_id": "b1_s1_w1_d1",
        "dialogue": [
            {"speaker": "Anna" if index % 2 == 0 else "Erik", "text": f"Line {index}"}
            for index in range(20)
        ],
        "comprehension_questions": [
            {"id": "q1", "question_sv": "Var ar de?"},
            {"id": "q2", "question_sv": "Vad hander?"},
            {"id": "q3", "question_sv": "Hur slutar dialogen?"},
        ],
    }

    generated = build_generated_lesson(draft, "gpt-test")

    assert generated["lesson_id"] == "b1_s1_w1_d1"
    assert generated["model"] == "gpt-test"
    assert generated["schema_version"] == 1
    assert datetime.fromisoformat(generated["generated_at"].replace("Z", "+00:00")).tzinfo == UTC


def test_generated_dialogue_context_omits_comprehension_questions():
    lesson = sample_generated_lesson()

    context = generated_dialogue_object(lesson)

    assert context["lesson_id"] == lesson["lesson_id"]
    assert context["dialogue"] == lesson["dialogue"]
    assert "comprehension_questions" not in context


def test_active_comprehension_questions_uses_current_question_before_next_button():
    lesson = sample_generated_lesson()
    state = {
        "current_question_id": "q1",
    }

    assert active_comprehension_questions_object(lesson, state) == [
        {"id": "q1", "question_sv": "Var ar de?"}
    ]


def test_active_comprehension_questions_moves_only_after_state_changes():
    lesson = sample_generated_lesson()
    state = {
        "current_question_id": "q2",
    }

    assert active_comprehension_questions_object(lesson, state) == [
        {"id": "q2", "question_sv": "Vad hander?"}
    ]


def test_active_comprehension_questions_uses_current_question_until_discussion():
    lesson = sample_generated_lesson()
    state = {
        "current_question_id": "q3",
    }

    assert active_comprehension_questions_object(lesson, state) == [
        {"id": "q3", "question_sv": "Hur slutar dialogen?"}
    ]


def test_active_comprehension_questions_returns_empty_in_discussion():
    lesson = sample_generated_lesson()
    state = {
        "phase": "discussion",
        "current_question_id": None,
    }

    assert active_comprehension_questions_object(lesson, state) == []


def test_active_translation_sentence_uses_current_index():
    state = sample_translation_state(current_translation_index=2)

    assert active_translation_sentence_object(state) == {
        "index": 2,
        "sentence_number": 3,
        "sentence_count": 5,
        "sentence_en": "Sentence 3",
    }


def test_interactor_lesson_state_trims_translation_quiz_to_active_sentence():
    state = sample_translation_state(current_translation_index=2)

    visible_state = interactor_lesson_state_object(state)

    assert visible_state["translation_quiz"]["sentences_en"] == ["Sentence 3"]
    assert visible_state["current_translation_index"] == 0
    assert state["translation_quiz"]["sentences_en"] == [
        "Sentence 1",
        "Sentence 2",
        "Sentence 3",
        "Sentence 4",
        "Sentence 5",
    ]


def test_generated_lesson_validation_rejects_wrong_line_count():
    draft = {
        "lesson_id": "b1_s1_w1_d1",
        "dialogue": [{"speaker": "Anna", "text": "Hej"}],
        "comprehension_questions": [],
    }

    try:
        validate_generated_lesson_draft(draft, {"id": "b1_s1_w1_d1"})
    except ValueError as error:
        assert "20 lines" in str(error)
    else:
        raise AssertionError("expected validation error")


def test_sanitized_interactor_response_clears_progression_patch_fields():
    response = sample_interactor_response(
        phase="discussion",
        current_question_id="q2",
    )

    sanitized = sanitized_interactor_response(response)

    assert sanitized["state_patch"]["phase"] is None
    assert sanitized["state_patch"]["current_question_id"] is None


def test_interactor_validation_rejects_discussion_phase_during_comprehension():
    response = sample_interactor_response(
        phase="discussion",
        current_question_id="q1",
    )

    try:
        validate_interactor_response(response, sample_generated_lesson(), sample_lesson_state(), "svar")
    except ValueError as error:
        assert "cannot advance lesson phase" in str(error)
    else:
        raise AssertionError("expected validation error")


def test_interactor_validation_rejects_translation_phase_during_comprehension():
    response = sample_interactor_response(phase="translation")

    try:
        validate_interactor_response(response, sample_generated_lesson(), sample_lesson_state(), "svar")
    except ValueError as error:
        assert "cannot advance lesson phase" in str(error)
    else:
        raise AssertionError("expected validation error")


def test_interactor_validation_rejects_discussion_text_before_discussion_phase():
    response = sample_interactor_response(
        assistant_text="Svaret är accepterat. Du kan nu läsa dialogen igen.",
    )

    try:
        validate_interactor_response(response, sample_generated_lesson(), sample_lesson_state(), "svar")
    except ValueError as error:
        assert "discussion-stage guidance" in str(error)
    else:
        raise AssertionError("expected validation error")


def test_interactor_validation_rejects_translation_quiz_without_ui_command():
    state = sample_lesson_state(
        phase="discussion",
        current_question_id=None,
    )
    response = sample_interactor_response(translation_quiz=sample_translation_quiz())

    try:
        validate_interactor_response(response, sample_generated_lesson(), state, "start quiz")
    except ValueError as error:
        assert "start-quiz UI command" in str(error)
    else:
        raise AssertionError("expected validation error")


def test_interactor_validation_accepts_translation_quiz_for_ui_command_in_discussion():
    state = sample_lesson_state(
        phase="discussion",
        current_question_id=None,
    )
    response = sample_interactor_response(translation_quiz=sample_translation_quiz())

    validate_interactor_response(
        response,
        sample_generated_lesson(),
        state,
        "SYSTEM_UI_ACTION: start_translation_quiz",
    )


def test_send_lesson_message_retries_invalid_interactor_response():
    calls = []

    async def fake_send_structured_request(*_, **kwargs):
        calls.append(kwargs["input_value"])
        if len(calls) == 1:
            return sample_interactor_response(
                assistant_text="Svaret är accepterat. Du kan nu läsa dialogen igen.",
                phase="discussion",
                current_question_id="q1",
            )
        return sample_interactor_response(
            assistant_text="Bra svar.",
            current_question_id="q1",
        )

    original_send_structured_request = openai_client.send_structured_request
    openai_client.send_structured_request = fake_send_structured_request
    try:
        response = asyncio.run(
            openai_client.send_lesson_message(
                sample_settings(),
                payload={"id": "b1_s1_w1_d1"},
                generated_lesson=sample_generated_lesson(),
                state=sample_lesson_state(phase="listening", current_question_id=None),
                chat_history=[],
                latest_user_message="svar",
                model="gpt-test",
                reasoning_effort="low",
            )
        )
    finally:
        openai_client.send_structured_request = original_send_structured_request

    assert response["assistant_text"] == "Bra svar."
    assert response["state_patch"]["current_question_id"] is None
    assert len(calls) == 2
    assert any("validation_error" in item["content"] for item in calls[1])


def test_interactor_response_json_is_serializable():
    response = {
        "assistant_text": "Bra.",
        "state_patch": {
            "phase": None,
            "current_question_id": None,
            "mistake_notes_add": [],
        },
        "translation_quiz": None,
    }
    assert json.loads(json.dumps(response))["assistant_text"] == "Bra."


def sample_generated_lesson():
    return {
        "lesson_id": "b1_s1_w1_d1",
        "dialogue": [
            {"speaker": "Anna" if index % 2 == 0 else "Erik", "text": f"Line {index}"}
            for index in range(20)
        ],
        "comprehension_questions": [
            {"id": "q1", "question_sv": "Var ar de?"},
            {"id": "q2", "question_sv": "Vad hander?"},
            {"id": "q3", "question_sv": "Hur slutar dialogen?"},
        ],
        "generated_at": "2026-05-24T00:00:00Z",
        "model": "gpt-test",
        "schema_version": 1,
    }


def sample_lesson_state(
    *,
    phase="comprehension",
    current_question_id="q1",
):
    return {
        "lesson_id": "b1_s1_w1_d1",
        "phase": phase,
        "current_question_id": current_question_id,
        "translation_quiz": None,
        "current_translation_index": None,
        "translation_attempts": [],
    }


def sample_interactor_response(
    *,
    assistant_text="Bra.",
    phase=None,
    current_question_id=None,
    translation_quiz=None,
):
    return {
        "assistant_text": assistant_text,
        "state_patch": {
            "phase": phase,
            "current_question_id": current_question_id,
            "mistake_notes_add": [],
        },
        "translation_quiz": translation_quiz,
    }


def sample_translation_quiz():
    return {
        "sentences_en": [
            "Sentence 1",
            "Sentence 2",
            "Sentence 3",
            "Sentence 4",
            "Sentence 5",
        ]
    }


def sample_settings():
    return Settings(
        openai_api_key="test-openai",
        gemini_api_key="test-gemini",
        app_jwt_secret="test-secret",
        apple_client_id="test-client",
        database_path=Path("test.db"),
    )


def sample_translation_state(current_translation_index=0):
    return {
        "lesson_id": "b1_s1_w1_d1",
        "phase": "translation",
        "current_question_id": "q3",
        "translation_quiz": {
            "sentences_en": [
                "Sentence 1",
                "Sentence 2",
                "Sentence 3",
                "Sentence 4",
                "Sentence 5",
            ]
        },
        "current_translation_index": current_translation_index,
        "translation_attempts": [],
    }
