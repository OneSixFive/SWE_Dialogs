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
    project_speaking_lesson_context,
)
from app.speaking_events import durable_speaking_event


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

    instructions = build_speaking_instructions(lesson, generated)

    assert "Övningen är strikt styrd" in instructions
    assert "neutral, modern och naturlig svensk accent" in instructions
    assert "anropar du `end_speaking_practice` exakt en gång" in instructions
    assert "Avslutningsturen efter svar 10 är inte en vanlig tur" in instructions
    assert "exakt två korta meningar" in instructions
    assert "Sluta tala direkt efter uppmaningen" in instructions
    assert "svar 10 har tagits emot" in instructions
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


def test_durable_speaking_events_keep_complete_turns_but_drop_streaming_deltas():
    response_event = {
        "type": "response.done",
        "response": {
            "id": "resp_complete_1",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_audio", "transcript": "Hej!"}],
                }
            ],
        },
    }

    durable = durable_speaking_event(response_event)

    assert durable is not None
    assert durable.event_key == "response:resp_complete_1"
    assert durable.payload == response_event
    assert durable_speaking_event(
        {"type": "response.output_audio.delta", "delta": "base64-audio"}
    ) is None
    assert durable_speaking_event(
        {"type": "conversation.item.input_audio_transcription.delta", "delta": "Hej"}
    ) is None


def test_registry_enforces_active_lease_cooldown_and_window():
    now = [100.0]
    registry = SpeakingSessionRegistry(clock=lambda: now[0])
    lease = registry.begin(
        7,
        lesson_id="lesson-a",
        timeout_seconds=600,
        cooldown_seconds=10,
        window_seconds=600,
        max_starts_per_window=2,
    )

    try:
        registry.begin(
            7,
            lesson_id="lesson-a",
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
            timeout_seconds=600,
            cooldown_seconds=10,
            window_seconds=600,
            max_starts_per_window=2,
        )
    except SpeakingSessionLimitError as error:
        assert error.status_code == 429
    else:
        raise AssertionError("Expected rolling-window rate rejection.")


def test_registry_retains_call_id_until_finish_or_drain():
    registry = SpeakingSessionRegistry(clock=lambda: 100.0)
    lease = registry.begin(
        7,
        lesson_id="lesson-a",
        timeout_seconds=600,
        cooldown_seconds=10,
        window_seconds=600,
        max_starts_per_window=2,
    )
    attached = registry.attach_call_id(7, "lesson-a", lease.session_id, "call_test")

    assert attached is not None
    assert attached.lesson_id == "lesson-a"
    assert attached.call_id == "call_test"
    assert registry.finish(7, "lesson-b", lease.session_id) is None
    assert registry.finish(7, "lesson-a", lease.session_id) == attached
    assert registry.finish(7, "lesson-a", lease.session_id) is None

    second = registry.begin(
        8,
        lesson_id="lesson-b",
        timeout_seconds=600,
        cooldown_seconds=10,
        window_seconds=600,
        max_starts_per_window=2,
    )
    registry.attach_call_id(8, "lesson-b", second.session_id, "call_shutdown")
    assert [item.call_id for item in registry.drain()] == ["call_shutdown"]


def test_registry_abort_does_not_charge_failed_start_against_cooldown():
    registry = SpeakingSessionRegistry(clock=lambda: 100.0)
    failed = registry.begin(
        7,
        lesson_id="lesson-a",
        timeout_seconds=600,
        cooldown_seconds=30,
        window_seconds=600,
        max_starts_per_window=1,
    )

    assert registry.abort(7, "lesson-a", failed.session_id) == failed
    retry = registry.begin(
        7,
        lesson_id="lesson-a",
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
    sideband_leases = []

    def fake_start_speaking_sideband(_registry, _settings, _database, lease):
        sideband_leases.append(lease)

    monkeypatch.setattr(main, "_start_speaking_sideband", fake_start_speaking_sideband)
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
                "Avsluta talövningen först efter elevens tionde innehållsliga svar och den "
                "fullständiga talade avslutningsturen med en innehållsspecifik reaktion och "
                "en avskedsfras. Avslutningsturen får inte innehålla en fråga eller ny "
                "svarsmöjlighet. Anropa aldrig verktyget tidigare."
                " Vänta tills det tionde svaret har tagits emot och bedömts och en eventuell rättelse "
                "med upprepning är klar. Anropa aldrig medan du väntar på eleven."
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
    assert len(sideband_leases) == 1
    assert sideband_leases[0].lesson_id == lesson_id
    assert sideband_leases[0].call_id == "call_test"

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
        lesson_id="lesson-a",
        timeout_seconds=1,
        cooldown_seconds=0,
        window_seconds=600,
        max_starts_per_window=2,
    )
    attached = registry.attach_call_id(9, "lesson-a", lease.session_id, "call_expired")
    assert attached is not None
    hangups = []

    async def fake_hangup_realtime_call(*_, call_id):
        hangups.append(call_id)

    monkeypatch.setattr(main, "hangup_realtime_call", fake_hangup_realtime_call)
    asyncio.run(main._expire_speaking_lease(registry, settings, attached))

    assert hangups == ["call_expired"]
    assert registry.finish(9, "lesson-a", lease.session_id) is None


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
    assert _call_id("https://api.openai.com/v1/realtime/calls/rtc_123") == "rtc_123"
    assert _call_id("https://api.openai.com/v1/realtime/calls/rtc_u1_abc-123") == "rtc_u1_abc-123"
    assert _call_id("https://api.openai.com/v1/realtime/calls/not-a-call") is None
    assert _call_id("https://api.openai.com/v1/realtime/calls/call_../../secrets") is None
    assert _call_id(None) is None


def test_sideband_transport_is_authenticated_read_only_and_bounded(monkeypatch, tmp_path):
    _, _, settings = make_client(tmp_path)
    captured = {}

    class FakeWebSocket:
        def __init__(self):
            self.messages = iter(['{"type":"session.created"}', b'{"type":"response.created"}'])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.messages)
            except StopIteration:
                raise StopAsyncIteration

    class FakeConnection:
        async def __aenter__(self):
            return FakeWebSocket()

        async def __aexit__(self, *_):
            return None

    def fake_connect(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeConnection()

    monkeypatch.setattr(realtime_client, "connect", fake_connect)

    async def collect():
        return [
            event
            async for event in realtime_client.realtime_sideband_events(
                settings,
                call_id="rtc_u1_test",
            )
        ]

    events = asyncio.run(collect())

    assert events == [{"type": "session.created"}, {"type": "response.created"}]
    assert captured["url"] == "wss://api.openai.com/v1/realtime?call_id=rtc_u1_test"
    assert captured["additional_headers"] == {"Authorization": "Bearer test-openai"}
    assert captured["max_size"] == 1024 * 1024


def test_sideband_records_response_done_idempotently(tmp_path, monkeypatch, caplog):
    caplog.set_level("INFO")
    _, database, settings = make_client(tmp_path)
    user = database.find_or_create_user("apple-sideband", None)
    registry = SpeakingSessionRegistry(clock=lambda: 100.0)
    lease = registry.begin(
        user.id,
        lesson_id="b1_stage_1_week_1_day_1",
        timeout_seconds=600,
        cooldown_seconds=0,
        window_seconds=600,
        max_starts_per_window=2,
    )
    attached = registry.attach_call_id(
        user.id,
        lease.lesson_id,
        lease.session_id,
        "rtc_sideband",
    )
    assert attached is not None
    event = {
        "event_id": "event_sideband_response_1",
        "type": "response.done",
        "response": {
            "id": "resp_sideband_1",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_audio",
                            "transcript": "Det låter bra. Vad gör du efter jobbet?",
                        }
                    ],
                },
                {
                    "type": "function_call",
                    "name": "end_speaking_practice",
                    "arguments": "{}",
                },
            ],
            "usage": {
                "total_tokens": 30,
                "input_tokens": 20,
                "output_tokens": 10,
                "input_token_details": {
                    "text_tokens": 5,
                    "audio_tokens": 15,
                    "image_tokens": 0,
                    "cached_tokens": 5,
                    "cached_tokens_details": {
                        "text_tokens": 5,
                        "audio_tokens": 0,
                        "image_tokens": 0,
                    },
                },
                "output_token_details": {"text_tokens": 2, "audio_tokens": 8},
            },
        },
    }
    speech_started = {
        "event_id": "event_speech_started_1",
        "type": "input_audio_buffer.speech_started",
        "audio_start_ms": 1200,
        "item_id": "item_learner_1",
    }
    speech_stopped = {
        "event_id": "event_speech_stopped_1",
        "type": "input_audio_buffer.speech_stopped",
        "audio_end_ms": 3200,
        "item_id": "item_learner_1",
    }
    learner_transcript = {
        "event_id": "event_transcript_1",
        "type": "conversation.item.input_audio_transcription.completed",
        "item_id": "item_learner_1",
        "content_index": 0,
        "transcript": "Efter jobbet går jag hem.",
    }

    async def fake_sideband_events(_settings, *, call_id):
        assert call_id == "rtc_sideband"
        yield speech_started
        yield speech_stopped
        yield learner_transcript
        yield event
        yield event
        registry.finish(user.id, lease.lesson_id, lease.session_id)

    monkeypatch.setattr(main, "realtime_sideband_events", fake_sideband_events)
    asyncio.run(main._run_speaking_sideband(registry, settings, database, attached))

    summary = database.usage_dashboard_summary(
        start_time="2000-01-01T00:00:00.000000Z",
        end_time="2100-01-01T00:00:00.000000Z",
        roles=["Speaking"],
    )
    assert summary.totals["request_count"] == 1
    assert summary.totals["total_tokens"] == 30
    stored_events = database.list_speaking_realtime_events(
        user_id=user.id,
        lesson_id=lease.lesson_id,
        session_id=lease.session_id,
    )
    assert [stored.event_type for stored in stored_events] == [
        "input_audio_buffer.speech_started",
        "input_audio_buffer.speech_stopped",
        "conversation.item.input_audio_transcription.completed",
        "response.done",
    ]
    assert stored_events[2].payload == learner_transcript
    assert stored_events[3].payload == event
    assert stored_events[3].provider_event_id == "event_sideband_response_1"
    assert stored_events[3].provider_response_id == "resp_sideband_1"
    other_user = database.find_or_create_user("apple-sideband-other", None)
    assert database.list_speaking_realtime_events(user_id=other_user.id) == []
    assert "speaking_event_recorded" in caplog.text
    assert "speaking_event_duplicate" in caplog.text
    assert "speaking_usage_recorded" in caplog.text
    assert "speaking_usage_duplicate" in caplog.text


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
