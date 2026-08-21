from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app import main
from app.auth import get_database, get_settings, issue_session_token
from app.config import Settings
from app.db import Database
from app.main import app
from app import realtime_client
from app.realtime_client import (
    RealtimeBootstrapError,
    RealtimeCallAnswer,
    _call_id,
    create_realtime_call,
    hangup_realtime_call,
)
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

    assert "Övningen är strikt styrd" in instructions
    assert "neutral, modern och naturlig svensk accent" in instructions
    assert "anropar du `end_speaking_practice` exakt en gång" in instructions
    assert "ROLE_GUIDANCE" not in instructions
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


def test_registry_retains_call_id_until_finish_or_drain():
    registry = SpeakingSessionRegistry(clock=lambda: 100.0)
    lease = registry.begin(
        7,
        timeout_seconds=600,
        cooldown_seconds=10,
        window_seconds=600,
        max_starts_per_window=2,
    )
    attached = registry.attach_call_id(7, lease.session_id, "call_test")

    assert attached is not None
    assert attached.call_id == "call_test"
    assert registry.finish(7, lease.session_id) == attached
    assert registry.finish(7, lease.session_id) is None

    second = registry.begin(
        8,
        timeout_seconds=600,
        cooldown_seconds=10,
        window_seconds=600,
        max_starts_per_window=2,
    )
    registry.attach_call_id(8, second.session_id, "call_shutdown")
    assert [item.call_id for item in registry.drain()] == ["call_shutdown"]


def test_registry_abort_does_not_charge_failed_start_against_cooldown():
    registry = SpeakingSessionRegistry(clock=lambda: 100.0)
    failed = registry.begin(
        7,
        timeout_seconds=600,
        cooldown_seconds=30,
        window_seconds=600,
        max_starts_per_window=1,
    )

    assert registry.abort(7, failed.session_id) == failed
    retry = registry.begin(
        7,
        timeout_seconds=600,
        cooldown_seconds=30,
        window_seconds=600,
        max_starts_per_window=1,
    )

    assert retry.session_id != failed.session_id


def test_realtime_rejection_exposes_only_safe_provider_metadata(monkeypatch, tmp_path):
    _, _, settings = make_client(tmp_path)

    class FakeAsyncClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, *_args, **_kwargs):
            return httpx.Response(
                400,
                json={
                    "error": {
                        "type": "invalid_request_error",
                        "code": "invalid_value",
                        "param": "session.audio.input.turn_detection.eagerness",
                        "message": "sensitive provider explanation must not be retained",
                    }
                },
                headers={"x-request-id": "req_safe-123"},
            )

    monkeypatch.setattr(realtime_client.httpx, "AsyncClient", FakeAsyncClient)

    try:
        asyncio.run(
            create_realtime_call(
                settings,
                sdp_offer="v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111",
                session_config={"type": "realtime"},
                safety_identifier="safe-id",
            )
        )
    except RealtimeBootstrapError as error:
        assert error.provider_status == 400
        assert error.provider_code == "invalid_value"
        assert error.provider_type == "invalid_request_error"
        assert error.provider_param == "session.audio.input.turn_detection.eagerness"
        assert error.request_id == "req_safe-123"
        assert "sensitive provider explanation" not in error.public_detail()
    else:
        raise AssertionError("Expected provider rejection.")


def test_realtime_call_preserves_sdp_crlf_in_both_directions(monkeypatch, tmp_path):
    _, _, settings = make_client(tmp_path)
    captured = {}
    offer = "v=0\r\no=- 1 2 IN IP4 127.0.0.1\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
    answer = "v=0\r\no=- 2 3 IN IP4 127.0.0.1\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"

    class FakeAsyncClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, *_args, **kwargs):
            captured["sdp"] = kwargs["files"]["sdp"][1]
            return httpx.Response(
                200,
                content=answer.encode("utf-8"),
                headers={"location": "https://api.openai.com/v1/realtime/calls/call_crlf"},
            )

    monkeypatch.setattr(realtime_client.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        create_realtime_call(
            settings,
            sdp_offer=offer,
            session_config={"type": "realtime"},
            safety_identifier="safe-id",
        )
    )

    assert captured["sdp"] == offer
    assert result.sdp == answer
    assert result.call_id == "call_crlf"


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
    hangups = []

    async def fake_hangup_realtime_call(*_, call_id):
        hangups.append(call_id)

    monkeypatch.setattr(main, "hangup_realtime_call", fake_hangup_realtime_call)
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
    assert 1 <= int(response.headers["x-speaking-session-timeout-seconds"]) <= 600
    assert captured["sdp_offer"] == sdp_offer
    assert captured["session_config"]["model"] == "gpt-realtime-2.1"
    assert captured["session_config"]["max_output_tokens"] == 1024
    assert captured["session_config"]["tool_choice"] == "auto"
    assert captured["session_config"]["tools"] == [
        {
            "type": "function",
            "name": "end_speaking_practice",
            "description": (
                "Avsluta talövningen efter elevens tionde innehållsliga svar och den korta "
                "muntliga avskedsfrasen. Anropa aldrig verktyget tidigare."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        }
    ]
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
    assert hangups == ["call_test"]


def test_expired_lease_hangs_up_provider_call(monkeypatch):
    registry = SpeakingSessionRegistry(clock=lambda: 0.0)
    settings = Settings(
        openai_api_key="test-openai",
        gemini_api_key="test-gemini",
        app_jwt_secret="test-secret",
        apple_client_id="test-client",
        database_path=Path("unused.db"),
    )
    lease = registry.begin(
        9,
        timeout_seconds=1,
        cooldown_seconds=0,
        window_seconds=600,
        max_starts_per_window=2,
    )
    attached = registry.attach_call_id(9, lease.session_id, "call_expired")
    assert attached is not None
    hangups = []

    async def fake_hangup_realtime_call(*_, call_id):
        hangups.append(call_id)

    monkeypatch.setattr(main, "hangup_realtime_call", fake_hangup_realtime_call)
    asyncio.run(main._expire_speaking_lease(registry, settings, attached))

    assert hangups == ["call_expired"]
    assert registry.finish(9, lease.session_id) is None


def test_hangup_realtime_call_uses_provider_endpoint(monkeypatch, tmp_path):
    captured = {}

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, url, *, headers):
            captured["url"] = url
            captured["headers"] = headers
            return httpx.Response(200)

    monkeypatch.setattr(realtime_client.httpx, "AsyncClient", FakeAsyncClient)
    _, _, settings = make_client(tmp_path)

    asyncio.run(hangup_realtime_call(settings, call_id="call_abc-123"))

    assert captured["url"] == "https://api.openai.com/v1/realtime/calls/call_abc-123/hangup"
    assert captured["headers"] == {"Authorization": "Bearer test-openai"}


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
    assert _call_id("https://api.openai.com/v1/realtime/calls/call_../../secrets") is None
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
