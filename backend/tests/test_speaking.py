from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import main
from app.auth import get_database, get_settings, issue_session_token
from app.config import Settings
from app.db import Database
from app.main import app
from app.realtime_client import RealtimeCallAnswer, _call_id
from app.speaking_service import (
    SpeakingContextError,
    SpeakingSessionLimitError,
    SpeakingSessionRegistry,
    build_speaking_instructions,
    project_reference_dialogue,
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


def test_speaking_instructions_include_full_lesson_and_only_projected_dialogue():
    lesson = main.get_learning_catalog().lesson("b1_stage_1_week_1_day_1")
    assert lesson is not None
    generated = generated_lesson(lesson.lesson_id)
    generated["unrelated_injection"] = "must-not-reach-speaking"
    generated["dialogue"][0]["hidden"] = "also-must-not-reach-speaking"

    instructions = build_speaking_instructions(lesson, generated)

    assert "guided/passive answer mode" in instructions
    assert '"translation_quiz"' in instructions
    assert '"speaker":"Anna"' in instructions
    assert "must-not-reach-speaking" not in instructions
    assert "also-must-not-reach-speaking" not in instructions


def test_registry_enforces_active_lease_cooldown_and_window():
    now = [100.0]
    registry = SpeakingSessionRegistry(clock=lambda: now[0])
    lease = registry.begin(
        7,
        timeout_seconds=600,
        cooldown_seconds=10,
        window_seconds=600,
        max_starts_per_window=2,
    )

    try:
        registry.begin(7, timeout_seconds=600, cooldown_seconds=10, window_seconds=600, max_starts_per_window=2)
    except SpeakingSessionLimitError as error:
        assert error.status_code == 409
    else:
        raise AssertionError("Expected active lease rejection.")

    registry.finish(7, lease.session_id)
    try:
        registry.begin(7, timeout_seconds=600, cooldown_seconds=10, window_seconds=600, max_starts_per_window=2)
    except SpeakingSessionLimitError as error:
        assert error.status_code == 429
    else:
        raise AssertionError("Expected cooldown rejection.")

    now[0] += 11
    second = registry.begin(7, timeout_seconds=600, cooldown_seconds=10, window_seconds=600, max_starts_per_window=2)
    registry.finish(7, second.session_id)
    now[0] += 11
    try:
        registry.begin(7, timeout_seconds=600, cooldown_seconds=10, window_seconds=600, max_starts_per_window=2)
    except SpeakingSessionLimitError as error:
        assert error.status_code == 429
    else:
        raise AssertionError("Expected rolling-window rate rejection.")


def test_speaking_endpoint_builds_server_owned_session_and_releases_lease(tmp_path, monkeypatch):
    client, database, settings = make_client(tmp_path)
    user = database.find_or_create_user("apple-speaking", None)
    headers = auth_headers(settings, user.apple_sub)
    lesson_id = "b1_stage_1_week_1_day_1"
    upload = client.put(
        f"/me/lesson-sessions/{lesson_id}",
        headers=headers,
        json=session_payload(lesson_id),
    )
    assert upload.status_code == 200

    captured = {}

    async def fake_create_realtime_call(*_, **kwargs):
        captured.update(kwargs)
        return RealtimeCallAnswer(
            sdp="v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n",
            call_id="call_test",
        )

    monkeypatch.setattr(main, "create_realtime_call", fake_create_realtime_call)
    monkeypatch.setattr(main, "speaking_sessions", SpeakingSessionRegistry())
    sdp_offer = "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
    response = client.post(
        f"/me/lesson-sessions/{lesson_id}/speaking/realtime-call",
        headers={**headers, "Content-Type": "application/sdp"},
        content=sdp_offer,
    )

    assert response.status_code == 201
    assert response.text.startswith("v=0")
    assert response.headers["x-realtime-call-id"] == "call_test"
    speaking_session_id = response.headers["x-speaking-session-id"]
    assert response.headers["x-speaking-session-timeout-seconds"] == "600"
    assert captured["sdp_offer"] == sdp_offer.strip()
    assert captured["session_config"]["model"] == "gpt-realtime-2.1"
    assert captured["session_config"]["max_output_tokens"] == 256
    assert captured["session_config"]["audio"]["input"]["turn_detection"] == {
        "type": "semantic_vad",
        "eagerness": "low",
        "create_response": True,
        "interrupt_response": True,
    }
    assert len(captured["safety_identifier"]) == 64

    duplicate = client.post(
        f"/me/lesson-sessions/{lesson_id}/speaking/realtime-call",
        headers={**headers, "Content-Type": "application/sdp"},
        content=sdp_offer,
    )
    assert duplicate.status_code == 409

    ended = client.delete(
        f"/me/lesson-sessions/{lesson_id}/speaking/realtime-call",
        headers={**headers, "X-Speaking-Session-ID": speaking_session_id},
    )
    assert ended.status_code == 204


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


def test_realtime_location_extracts_only_call_ids():
    assert _call_id("https://api.openai.com/v1/realtime/calls/call_123") == "call_123"
    assert _call_id("https://api.openai.com/v1/realtime/calls/not-a-call") is None
    assert _call_id(None) is None


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
