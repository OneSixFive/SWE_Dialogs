from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import get_database, get_settings, issue_session_token
from app.config import Settings
from app.db import Database
from app.learning_catalog import LearningCatalog
from app.main import app


def test_lesson_session_upsert_and_read_is_user_scoped(tmp_path):
    client, database, settings = make_client(tmp_path)
    user_a = database.find_or_create_user("apple-a", "a@example.com")
    user_b = database.find_or_create_user("apple-b", "b@example.com")

    response = client.put(
        "/me/lesson-sessions/b1_s1_w1_d1",
        headers=auth_headers(settings, user_a.apple_sub),
        json=session_payload("b1_s1_w1_d1"),
    )

    assert response.status_code == 200
    stored = response.json()
    assert stored["lesson_id"] == "b1_s1_w1_d1"
    assert stored["status"] == "generated"
    assert stored["generated_lesson"]["lesson_id"] == "b1_s1_w1_d1"
    assert stored["messages"][0]["content"] == "Hej"
    assert "apple_sub" not in client.get("/me", headers=auth_headers(settings, user_a.apple_sub)).json()

    read_a = client.get(
        "/me/lesson-sessions/b1_s1_w1_d1",
        headers=auth_headers(settings, user_a.apple_sub),
    )
    assert read_a.status_code == 200
    assert read_a.json()["state"]["lesson_id"] == "b1_s1_w1_d1"

    read_b = client.get(
        "/me/lesson-sessions/b1_s1_w1_d1",
        headers=auth_headers(settings, user_b.apple_sub),
    )
    assert read_b.status_code == 404

    list_b = client.get(
        "/me/lesson-sessions?summary_only=false",
        headers=auth_headers(settings, user_b.apple_sub),
    )
    assert list_b.status_code == 200
    assert list_b.json()["sessions"] == []


def test_completed_lesson_progress_sync_backfills_valid_ids_without_evaluation(tmp_path):
    client, database, settings = make_client(tmp_path)
    user = database.find_or_create_user("apple-a", None)
    headers = auth_headers(settings, user.apple_sub)
    catalog = LearningCatalog.load()
    completed_ids = [lesson.lesson_id for lesson in catalog.lessons[:130]]

    response = client.post(
        "/me/lesson-progress/sync",
        headers=headers,
        json={"completed_lesson_ids": completed_ids},
    )

    assert response.status_code == 200
    assert response.json() == {
        "completed_count": 130,
        "course_level": "B2",
        "stage_number": 1,
        "current_lesson_id": "b2_stage_1_week_3_day_5",
    }
    assert database.completed_lesson_ids(user_id=user.id) == set(completed_ids)
    with database._connect() as connection:
        jobs = connection.execute(
            "SELECT COUNT(*) AS count FROM evaluation_jobs WHERE user_id = ?",
            (user.id,),
        ).fetchone()
    assert jobs["count"] == 0

    restored = client.get(
        "/me/lesson-sessions?summary_only=false",
        headers=headers,
    )
    assert restored.status_code == 200
    restored_sessions = restored.json()["sessions"]
    assert len(restored_sessions) == 130
    assert restored_sessions[0]["lesson_id"] == completed_ids[0]
    assert restored_sessions[0]["status"] == "completed"
    assert restored_sessions[0]["is_completed"] is True
    assert restored_sessions[0]["state"] == {
        "lesson_id": completed_ids[0],
        "phase": "completed",
        "current_question_id": None,
        "translation_quiz": None,
        "current_translation_index": None,
        "translation_attempts": [],
        "mistake_notes": [],
        "audio_file_name": None,
        "is_completed": True,
        "updated_at": restored_sessions[0]["client_updated_at"],
    }
    assert restored_sessions[0]["generated_lesson"] is None
    assert restored_sessions[0]["messages"] == []


def test_completed_lesson_progress_sync_rejects_unknown_ids(tmp_path):
    client, database, settings = make_client(tmp_path)
    user = database.find_or_create_user("apple-a", None)

    response = client.post(
        "/me/lesson-progress/sync",
        headers=auth_headers(settings, user.apple_sub),
        json={"completed_lesson_ids": ["not-a-curriculum-lesson"]},
    )

    assert response.status_code == 422
    assert database.completed_lesson_ids(user_id=user.id) == set()


def test_completed_lesson_restore_does_not_duplicate_real_session(tmp_path):
    client, database, settings = make_client(tmp_path)
    user = database.find_or_create_user("apple-a", None)
    headers = auth_headers(settings, user.apple_sub)

    sync_response = client.post(
        "/me/lesson-progress/sync",
        headers=headers,
        json={"completed_lesson_ids": ["b1_stage_1_week_1_day_1"]},
    )
    assert sync_response.status_code == 200

    upsert_response = client.put(
        "/me/lesson-sessions/b1_stage_1_week_1_day_1",
        headers=headers,
        json=session_payload(
            "b1_stage_1_week_1_day_1",
            phase="completed",
            is_completed=True,
        ),
    )
    assert upsert_response.status_code == 200

    restored = client.get(
        "/me/lesson-sessions?summary_only=false",
        headers=headers,
    )
    assert restored.status_code == 200
    restored_sessions = restored.json()["sessions"]
    assert [session["lesson_id"] for session in restored_sessions] == ["b1_stage_1_week_1_day_1"]
    assert restored_sessions[0]["generated_lesson"]["lesson_id"] == "b1_stage_1_week_1_day_1"


def test_completed_lesson_audio_upload_and_read_is_user_scoped(tmp_path):
    client, database, settings = make_client(tmp_path)
    user_a = database.find_or_create_user("apple-a", None)
    user_b = database.find_or_create_user("apple-b", None)
    headers_a = auth_headers(settings, user_a.apple_sub)
    headers_b = auth_headers(settings, user_b.apple_sub)

    completed = client.put(
        "/me/lesson-sessions/b1_stage_1_week_1_day_1",
        headers=headers_a,
        json=session_payload(
            "b1_stage_1_week_1_day_1",
            phase="completed",
            is_completed=True,
        ),
    )
    assert completed.status_code == 200
    assert completed.json()["has_audio"] is False

    audio_data = wav_bytes(b"lesson-one")
    upload = client.put(
        "/me/lesson-sessions/b1_stage_1_week_1_day_1/audio",
        headers={**headers_a, "Content-Type": "audio/wav"},
        content=audio_data,
    )
    assert upload.status_code == 200
    assert upload.json()["has_audio"] is True
    assert upload.json()["byte_count"] == len(audio_data)

    restored = client.get(
        "/me/lesson-sessions/b1_stage_1_week_1_day_1",
        headers=headers_a,
    )
    assert restored.status_code == 200
    assert restored.json()["has_audio"] is True
    assert restored.json()["state"]["audio_file_name"] is None

    download_a = client.get(
        "/me/lesson-sessions/b1_stage_1_week_1_day_1/audio",
        headers=headers_a,
    )
    assert download_a.status_code == 200
    assert download_a.headers["content-type"] == "audio/wav"
    assert download_a.content == audio_data

    download_b = client.get(
        "/me/lesson-sessions/b1_stage_1_week_1_day_1/audio",
        headers=headers_b,
    )
    assert download_b.status_code == 404


def test_lesson_audio_requires_completed_lesson(tmp_path):
    client, database, settings = make_client(tmp_path)
    user = database.find_or_create_user("apple-a", None)
    headers = auth_headers(settings, user.apple_sub)

    generated = client.put(
        "/me/lesson-sessions/b1_stage_1_week_1_day_1",
        headers=headers,
        json=session_payload("b1_stage_1_week_1_day_1"),
    )
    assert generated.status_code == 200

    upload = client.put(
        "/me/lesson-sessions/b1_stage_1_week_1_day_1/audio",
        headers={**headers, "Content-Type": "audio/wav"},
        content=wav_bytes(b"not-complete"),
    )
    assert upload.status_code == 409


def test_completed_lesson_audio_retains_only_five_newest_per_user(tmp_path):
    client, database, settings = make_client(tmp_path)
    user = database.find_or_create_user("apple-a", None)
    headers = auth_headers(settings, user.apple_sub)
    lesson_ids = [f"b1_stage_1_week_1_day_{day}" for day in range(1, 7)]

    for day, lesson_id in enumerate(lesson_ids, start=1):
        completed_at = f"2026-05-{20 + day:02d}T12:00:00Z"
        completed = client.put(
            f"/me/lesson-sessions/{lesson_id}",
            headers=headers,
            json=session_payload(
                lesson_id,
                phase="completed",
                is_completed=True,
                completed_at=completed_at,
            ),
        )
        assert completed.status_code == 200
        uploaded = client.put(
            f"/me/lesson-sessions/{lesson_id}/audio",
            headers={**headers, "Content-Type": "audio/wav"},
            content=wav_bytes(f"lesson-{day}".encode("utf-8")),
        )
        assert uploaded.status_code == 200

    pruned = client.get(
        f"/me/lesson-sessions/{lesson_ids[0]}/audio",
        headers=headers,
    )
    retained = client.get(
        f"/me/lesson-sessions/{lesson_ids[1]}/audio",
        headers=headers,
    )
    assert pruned.status_code == 404
    assert retained.status_code == 200

    restored = client.get(
        "/me/lesson-sessions?summary_only=false",
        headers=headers,
    )
    assert restored.status_code == 200
    audio_flags = {
        session["lesson_id"]: session["has_audio"]
        for session in restored.json()["sessions"]
        if session["lesson_id"] in lesson_ids
    }
    assert audio_flags == {
        lesson_ids[0]: False,
        lesson_ids[1]: True,
        lesson_ids[2]: True,
        lesson_ids[3]: True,
        lesson_ids[4]: True,
        lesson_ids[5]: True,
    }


def test_openai_usage_summary_is_user_scoped_and_role_filterable(tmp_path):
    _, database, _ = make_client(tmp_path)
    user_a = database.find_or_create_user("apple-a", "a@example.com")
    user_b = database.find_or_create_user("apple-b", "b@example.com")

    database.record_openai_usage(
        {
            "user_id": user_a.id,
            "request_role": "Interactor",
            "request_name": "lesson_interactor",
            "source_id": "b1_s1_w1_d1",
            "model": "gpt-test",
            "input_tokens": 100,
            "cached_tokens": 25,
            "output_tokens": 50,
            "reasoning_tokens": 10,
            "total_tokens": 150,
            "estimated_cost_usd": 0.001,
            "elapsed_ms": 900,
            "created_at": "2026-06-10T12:00:00.000000Z",
            "raw_usage": {"input_tokens": 100},
        }
    )
    database.record_openai_usage(
        {
            "user_id": user_b.id,
            "request_role": "Evaluator",
            "request_name": "learning_evaluator",
            "source_id": "b1_s1_w1_d1",
            "model": "gpt-test",
            "input_tokens": 200,
            "cached_tokens": 0,
            "output_tokens": 100,
            "reasoning_tokens": 40,
            "total_tokens": 300,
            "estimated_cost_usd": 0.004,
            "elapsed_ms": 1200,
            "created_at": "2026-06-10T13:00:00.000000Z",
            "raw_usage": {"input_tokens": 200},
        }
    )

    summary = database.usage_dashboard_summary(
        start_time="2026-06-01T00:00:00.000000Z",
        end_time="2026-07-01T00:00:00.000000Z",
    )
    filtered = database.usage_dashboard_summary(
        start_time="2026-06-01T00:00:00.000000Z",
        end_time="2026-07-01T00:00:00.000000Z",
        roles=["Interactor"],
    )

    assert summary.totals["request_count"] == 2
    assert summary.totals["total_tokens"] == 450
    assert summary.totals["estimated_cost_usd"] == 0.005
    assert [row["email"] for row in summary.users] == ["b@example.com", "a@example.com"]
    assert summary.user_models == [
        {
            "user_id": user_a.id,
            "model": "gpt-test",
            "request_count": 1,
            "input_tokens": 100,
            "cached_tokens": 25,
            "output_tokens": 50,
            "reasoning_tokens": 10,
            "total_tokens": 150,
            "estimated_cost_usd": 0.001,
            "actual_cost_usd": 0.0,
        },
        {
            "user_id": user_b.id,
            "model": "gpt-test",
            "request_count": 1,
            "input_tokens": 200,
            "cached_tokens": 0,
            "output_tokens": 100,
            "reasoning_tokens": 40,
            "total_tokens": 300,
            "estimated_cost_usd": 0.004,
            "actual_cost_usd": 0.0,
        },
    ]
    assert filtered.totals["request_count"] == 1
    assert filtered.users == [
        {
            "user_id": user_a.id,
            "email": "a@example.com",
            "request_count": 1,
            "input_tokens": 100,
            "cached_tokens": 25,
            "output_tokens": 50,
            "reasoning_tokens": 10,
            "total_tokens": 150,
            "estimated_cost_usd": 0.001,
            "actual_cost_usd": 0.0,
        },
        {
            "user_id": user_b.id,
            "email": "b@example.com",
            "request_count": 0,
            "input_tokens": 0,
            "cached_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "actual_cost_usd": 0.0,
        },
    ]
    assert filtered.user_models == [
        {
            "user_id": user_a.id,
            "model": "gpt-test",
            "request_count": 1,
            "input_tokens": 100,
            "cached_tokens": 25,
            "output_tokens": 50,
            "reasoning_tokens": 10,
            "total_tokens": 150,
            "estimated_cost_usd": 0.001,
            "actual_cost_usd": 0.0,
        },
    ]


def test_lesson_session_stale_non_completed_write_conflicts(tmp_path):
    client, database, settings = make_client(tmp_path)
    user = database.find_or_create_user("apple-a", None)
    headers = auth_headers(settings, user.apple_sub)

    initial = client.put(
        "/me/lesson-sessions/b1_s1_w1_d1",
        headers=headers,
        json=session_payload("b1_s1_w1_d1"),
    )
    assert initial.status_code == 200
    server_updated_at = initial.json()["server_updated_at"]

    current = client.put(
        "/me/lesson-sessions/b1_s1_w1_d1",
        headers=headers,
        json=session_payload(
            "b1_s1_w1_d1",
            phase="comprehension",
            base_server_updated_at=server_updated_at,
        ),
    )
    assert current.status_code == 200

    stale = client.put(
        "/me/lesson-sessions/b1_s1_w1_d1",
        headers=headers,
        json=session_payload(
            "b1_s1_w1_d1",
            phase="listening",
            base_server_updated_at=server_updated_at,
        ),
    )

    assert stale.status_code == 409
    assert stale.json()["detail"]["current"]["status"] == "comprehension"


def test_completed_state_can_advance_stale_non_completed_state(tmp_path):
    client, database, settings = make_client(tmp_path)
    user = database.find_or_create_user("apple-a", None)
    headers = auth_headers(settings, user.apple_sub)

    initial = client.put(
        "/me/lesson-sessions/b1_s1_w1_d1",
        headers=headers,
        json=session_payload("b1_s1_w1_d1"),
    )
    assert initial.status_code == 200
    stale_base = initial.json()["server_updated_at"]

    current = client.put(
        "/me/lesson-sessions/b1_s1_w1_d1",
        headers=headers,
        json=session_payload(
            "b1_s1_w1_d1",
            phase="translation",
            base_server_updated_at=stale_base,
        ),
    )
    assert current.status_code == 200

    completed = client.put(
        "/me/lesson-sessions/b1_s1_w1_d1",
        headers=headers,
        json=session_payload(
            "b1_s1_w1_d1",
            phase="completed",
            is_completed=True,
            base_server_updated_at=stale_base,
        ),
    )

    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["is_completed"] is True
    assert completed.json()["completed_at"] is not None


def test_reset_requires_current_base_server_updated_at(tmp_path):
    client, database, settings = make_client(tmp_path)
    user = database.find_or_create_user("apple-a", None)
    headers = auth_headers(settings, user.apple_sub)

    initial = client.put(
        "/me/lesson-sessions/b1_s1_w1_d1",
        headers=headers,
        json=session_payload("b1_s1_w1_d1"),
    )
    assert initial.status_code == 200
    stale_base = initial.json()["server_updated_at"]

    current = client.put(
        "/me/lesson-sessions/b1_s1_w1_d1",
        headers=headers,
        json=session_payload(
            "b1_s1_w1_d1",
            phase="comprehension",
            base_server_updated_at=stale_base,
        ),
    )
    assert current.status_code == 200

    stale_reset = client.post(
        "/me/lesson-sessions/b1_s1_w1_d1/reset",
        headers=headers,
        json={"base_server_updated_at": stale_base},
    )
    assert stale_reset.status_code == 409

    reset = client.post(
        "/me/lesson-sessions/b1_s1_w1_d1/reset",
        headers=headers,
        json={"base_server_updated_at": current.json()["server_updated_at"]},
    )
    assert reset.status_code == 200
    assert reset.json()["status"] == "not_started"
    assert reset.json()["messages"] == []
    assert reset.json()["generated_lesson"] is None


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
    token = issue_session_token(apple_sub, settings)
    return {"Authorization": f"Bearer {token}"}


def session_payload(
    lesson_id: str,
    *,
    phase: str = "generated",
    is_completed: bool = False,
    base_server_updated_at: str | None = None,
    completed_at: str | None = None,
) -> dict:
    state = {
        "lesson_id": lesson_id,
        "phase": phase,
        "current_question_id": None,
        "translation_quiz": None,
        "current_translation_index": None,
        "translation_attempts": [],
        "mistake_notes": [],
        "audio_file_name": None,
        "is_completed": is_completed,
        "updated_at": "2026-05-26T12:00:00Z",
    }
    if completed_at is not None:
        state["completed_at"] = completed_at

    return {
        "state": state,
        "generated_lesson": {
            "lesson_id": lesson_id,
            "dialogue": [
                {"speaker": "Anna" if index % 2 == 0 else "Erik", "text": f"Line {index}"}
                for index in range(20)
            ],
            "comprehension_questions": [
                {"id": "q1", "question_sv": "Var ar de?"},
                {"id": "q2", "question_sv": "Vad hander?"},
                {"id": "q3", "question_sv": "Hur slutar det?"},
            ],
            "generated_at": "2026-05-26T12:00:00Z",
            "model": "gpt-test",
            "schema_version": 1,
        },
        "messages": [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "lesson_id": lesson_id,
                "role": "assistant",
                "content": "Hej",
                "created_at": "2026-05-26T12:00:00Z",
            }
        ],
        "client_updated_at": "2026-05-26T12:00:00Z",
        "base_server_updated_at": base_server_updated_at,
    }


def wav_bytes(payload: bytes) -> bytes:
    return b"RIFF" + len(payload).to_bytes(4, "little") + b"WAVEfmt " + payload
