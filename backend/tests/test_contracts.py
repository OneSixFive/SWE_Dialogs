import json
from datetime import UTC, datetime

from app.openai_client import (
    active_comprehension_questions_object,
    build_generated_lesson,
    course_context_object,
    generated_dialogue_object,
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
        "accepted_question_ids": ["q1"],
    }

    assert active_comprehension_questions_object(lesson, state) == [
        {"id": "q1", "question_sv": "Var ar de?"}
    ]


def test_active_comprehension_questions_moves_only_after_state_changes():
    lesson = sample_generated_lesson()
    state = {
        "current_question_id": "q2",
        "accepted_question_ids": ["q1"],
    }

    assert active_comprehension_questions_object(lesson, state) == [
        {"id": "q2", "question_sv": "Vad hander?"}
    ]


def test_active_comprehension_questions_returns_all_after_completion():
    lesson = sample_generated_lesson()
    state = {
        "current_question_id": "q3",
        "accepted_question_ids": ["q1", "q2", "q3"],
    }

    assert active_comprehension_questions_object(lesson, state) == lesson["comprehension_questions"]


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


def test_interactor_validation_rejects_unknown_question_id():
    response = {
        "assistant_text": "Bra.",
        "state_patch": {
            "phase": "comprehension",
            "current_question_id": "missing",
            "accepted_question_ids_add": [],
            "mistake_notes_add": [],
        },
        "translation_quiz": None,
    }
    lesson = {
        "comprehension_questions": [
            {"id": "q1", "question_sv": "Var ar de?"},
        ]
    }

    try:
        validate_interactor_response(response, lesson)
    except ValueError as error:
        assert "unknown question" in str(error)
    else:
        raise AssertionError("expected validation error")


def test_interactor_response_json_is_serializable():
    response = {
        "assistant_text": "Bra.",
        "state_patch": {
            "phase": None,
            "current_question_id": None,
            "accepted_question_ids_add": [],
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
