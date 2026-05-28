from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import get_database, get_settings, issue_session_token
from app.config import Settings
from app.db import Database
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
) -> dict:
    return {
        "state": {
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
        },
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
