from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import main
from app.auth import get_database, get_settings, issue_session_token
from app.config import Settings
from app.db import Database
from app.main import app
from app.speaking_service import (
    SpeakingContextError,
    SpeakingSessionLimitError,
    SpeakingSessionRegistry,
    build_speaker_instructions,
    project_reference_dialogue,
    project_speaking_lesson_context,
)


def test_reference_dialogue_projection_is_bounded_and_drops_unrelated_fields():
    generated = generated_lesson("b1_stage_1_week_1_day_1")
    generated["unrelated_injection"] = "must-not-reach-speaking"
    generated["dialogue"][0]["hidden"] = "also-must-not-reach-speaking"
    generated["dialogue"][0]["text"] = "  Hej!  "

    projected = project_reference_dialogue(
        generated,
        expected_lesson_id="b1_stage_1_week_1_day_1",
    )

    assert len(projected) == 20
    assert projected[0] == {"speaker": "Anna", "text": "Hej!"}
    assert all(set(line) == {"speaker", "text"} for line in projected)


def test_reference_dialogue_projection_rejects_invalid_shape():
    generated = generated_lesson("b1_stage_1_week_1_day_1")
    generated["dialogue"][4]["speaker"] = "System"

    try:
        project_reference_dialogue(generated, expected_lesson_id="b1_stage_1_week_1_day_1")
    except SpeakingContextError as error:
        assert "invalid speaker" in str(error)
    else:
        raise AssertionError("Expected invalid dialogue speaker to be rejected.")


def test_speaking_lesson_context_keeps_only_conversation_guidance():
    lesson = main.get_learning_catalog().lesson("b1_stage_1_week_1_day_2")
    assert lesson is not None

    context = project_speaking_lesson_context(lesson)

    assert set(context) == {
        "id",
        "difficulty",
        "communicative_goal",
        "scenario",
        "grammar_focus",
        "rough_structure",
    }
    assert set(context["grammar_focus"]) == {"name", "description"}
    assert set(context["rough_structure"]) == {"opening", "middle", "ending"}
    assert context["grammar_focus"]["name"] == "V2 word order after time expressions"
    assert "model_examples" not in context["grammar_focus"]
    assert "desired_presence" not in context["grammar_focus"]


def test_speaking_instructions_include_only_projected_lesson_and_dialogue():
    lesson = main.get_learning_catalog().lesson("b1_stage_1_week_1_day_2")
    assert lesson is not None
    generated = generated_lesson(lesson.lesson_id)
    generated["unrelated_injection"] = "must-not-reach-speaking"
    generated["dialogue"][0]["hidden"] = "also-must-not-reach-speaking"

    instructions = build_speaker_instructions(lesson, generated)

    assert "Övningen är strikt styrd" in instructions
    assert "`closing_if_accepted`" in instructions
    assert "exakt två korta meningar" in instructions
    assert "Sluta direkt efter uppmaningen" in instructions
    assert "ROLE_GUIDANCE" not in instructions
    assert '"communicative_goal"' in instructions
    assert '"grammar_focus"' in instructions
    assert '"rough_structure"' in instructions
    assert '"translation_quiz"' not in instructions
    assert '"comprehension_questions"' not in instructions
    assert '"model_examples"' not in instructions
    assert '"desired_presence"' not in instructions
    assert '"useful_chunks"' not in instructions
    assert '"repetition"' not in instructions
    assert "Använd två eller tre korta meningar per vanlig tur" not in instructions
    assert "Använd lektionens grammatik, ord och fraser naturligt" not in instructions
    assert "gestalta den själv" not in instructions
    assert '"speaker":"Anna"' in instructions
    assert "must-not-reach-speaking" not in instructions
    assert "also-must-not-reach-speaking" not in instructions


def test_registry_enforces_active_lease_cooldown_and_window():
    now = [100.0]
    registry = SpeakingSessionRegistry(clock=lambda: now[0])
    lease = registry.begin(
        7,
        lesson_id="lesson-a",
        instructions="test",
        transcription_context="test",
        timeout_seconds=600,
        cooldown_seconds=10,
        window_seconds=600,
        max_starts_per_window=2,
    )

    try:
        registry.begin(
            7,
            lesson_id="lesson-a",
            instructions="test",
            transcription_context="test",
            timeout_seconds=600,
            cooldown_seconds=10,
            window_seconds=600,
            max_starts_per_window=2,
        )
    except SpeakingSessionLimitError as error:
        assert error.status_code == 409
    else:
        raise AssertionError("Expected active lease rejection.")

    registry.finish(7, "lesson-a", lease.session_id)
    try:
        registry.begin(
            7,
            lesson_id="lesson-a",
            instructions="test",
            transcription_context="test",
            timeout_seconds=600,
            cooldown_seconds=10,
            window_seconds=600,
            max_starts_per_window=2,
        )
    except SpeakingSessionLimitError as error:
        assert error.status_code == 429
    else:
        raise AssertionError("Expected cooldown rejection.")

    now[0] += 11
    second = registry.begin(
        7,
        lesson_id="lesson-a",
        instructions="test",
        transcription_context="test",
        timeout_seconds=600,
        cooldown_seconds=10,
        window_seconds=600,
        max_starts_per_window=2,
    )
    registry.finish(7, "lesson-a", second.session_id)
    now[0] += 11
    try:
        registry.begin(
            7,
            lesson_id="lesson-a",
            instructions="test",
            transcription_context="test",
            timeout_seconds=600,
            cooldown_seconds=10,
            window_seconds=600,
            max_starts_per_window=2,
        )
    except SpeakingSessionLimitError as error:
        assert error.status_code == 429
    else:
        raise AssertionError("Expected rolling-window rate rejection.")


def test_registry_abort_does_not_charge_failed_start_against_cooldown():
    registry = SpeakingSessionRegistry(clock=lambda: 100.0)
    failed = registry.begin(
        7,
        lesson_id="lesson-a",
        instructions="test",
        transcription_context="test",
        timeout_seconds=600,
        cooldown_seconds=30,
        window_seconds=600,
        max_starts_per_window=1,
    )

    assert registry.abort(7, "lesson-a", failed.session_id) == failed
    retry = registry.begin(
        7,
        lesson_id="lesson-a",
        instructions="test",
        transcription_context="test",
        timeout_seconds=600,
        cooldown_seconds=30,
        window_seconds=600,
        max_starts_per_window=1,
    )

    assert retry.session_id != failed.session_id


def test_normal_session_upload_rejects_invalid_generated_dialogue(tmp_path):
    client, database, settings = make_client(tmp_path)
    user = database.find_or_create_user("apple-speaking", None)
    payload = session_payload("b1_stage_1_week_1_day_1")
    payload["generated_lesson"]["dialogue"] = payload["generated_lesson"]["dialogue"][:-1]

    response = client.put(
        "/me/lesson-sessions/b1_stage_1_week_1_day_1",
        headers=auth_headers(settings, user.apple_sub),
        json=payload,
    )

    assert response.status_code == 422
    assert "exactly 20 lines" in response.text


def make_client(tmp_path: Path):
    settings = Settings(
        openai_api_key="test-openai",
        gemini_api_key="test-gemini",
        app_jwt_secret="test-secret",
        apple_client_id="test-client",
        database_path=tmp_path / "svenska.db",
    )
    database = Database(settings.database_path)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_database] = lambda: database
    return TestClient(app), database, settings


def auth_headers(settings: Settings, apple_sub: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_session_token(apple_sub, settings)}"}


def generated_lesson(lesson_id: str) -> dict:
    return {
        "lesson_id": lesson_id,
        "dialogue": [
            {"speaker": "Anna" if index % 2 == 0 else "Erik", "text": f"Line {index + 1}"}
            for index in range(20)
        ],
        "comprehension_questions": [
            {"id": "q1", "question_sv": "Vad händer?"},
            {"id": "q2", "question_sv": "Varför?"},
            {"id": "q3", "question_sv": "Hur slutar det?"},
        ],
        "generated_at": "2026-08-21T10:00:00Z",
        "model": "gpt-test",
        "schema_version": 1,
    }


def session_payload(lesson_id: str) -> dict:
    return {
        "state": {
            "lesson_id": lesson_id,
            "phase": "generated",
            "current_question_id": None,
            "translation_quiz": None,
            "current_translation_index": None,
            "translation_attempts": [],
            "mistake_notes": [],
            "audio_file_name": None,
            "is_completed": False,
            "updated_at": "2026-08-21T10:00:00Z",
        },
        "generated_lesson": generated_lesson(lesson_id),
        "messages": [],
        "client_updated_at": "2026-08-21T10:00:00Z",
        "base_server_updated_at": None,
    }
