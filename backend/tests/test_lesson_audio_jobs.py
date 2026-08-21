from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import get_database, get_settings, issue_session_token
from app.config import Settings
from app.db import Database
from app.lesson_audio_worker import process_one_lesson_audio
from app.main import app


LESSON_ID = "b1_stage_1_week_1_day_1"


def test_generate_is_idempotent_and_user_scoped(tmp_path: Path):
    client, database, settings = make_client(tmp_path)
    user = database.find_or_create_user("audio-user", None)
    other = database.find_or_create_user("other-user", None)
    store_generated_session(client, settings, user.apple_sub)

    first = client.post(audio_generate_path(), headers=auth_headers(settings, user.apple_sub))
    second = client.post(audio_generate_path(), headers=auth_headers(settings, user.apple_sub))

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["content_hash"] == second.json()["content_hash"]
    with database._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM lesson_audio_jobs").fetchone()[0] == 1

    isolated = client.get(audio_status_path(), headers=auth_headers(settings, other.apple_sub))
    assert isolated.status_code == 200
    assert isolated.json() == {
        "lesson_id": LESSON_ID,
        "content_hash": None,
        "status": "missing",
        "attempt_count": 0,
        "retryable": True,
        "updated_at": None,
        "error_code": None,
    }


def test_concurrent_requests_resolve_to_one_job(tmp_path: Path):
    _, database, _ = make_client(tmp_path)
    user = database.find_or_create_user("audio-user", None)
    database.upsert_lesson_session(
        user_id=user.id,
        lesson_id=LESSON_ID,
        state=lesson_state(),
        generated_lesson=generated_lesson(),
        messages=[],
        chat_summary=None,
        client_updated_at="2026-08-20T10:00:00Z",
        base_server_updated_at=None,
        reset_generation=False,
    )

    def request_job():
        return database.request_lesson_audio_job(
            user_id=user.id,
            lesson_id=LESSON_ID,
            max_queued_per_user=5,
            retry_cooldown_seconds=0,
        )[0]

    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = list(pool.map(lambda _: request_job(), range(6)))

    assert len({job.id for job in jobs if job is not None}) == 1
    with database._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM lesson_audio_jobs").fetchone()[0] == 1


def test_worker_stores_valid_hash_bound_audio_and_download_metadata(tmp_path: Path, monkeypatch):
    client, database, settings = make_client(tmp_path)
    user = database.find_or_create_user("audio-user", None)
    store_generated_session(client, settings, user.apple_sub)
    queued = client.post(audio_generate_path(), headers=auth_headers(settings, user.apple_sub))
    expected_hash = queued.json()["content_hash"]
    wav = valid_wav()

    async def fake_generate(*_args, **_kwargs):
        return wav

    monkeypatch.setattr("app.lesson_audio_worker.generate_wav", fake_generate)
    assert asyncio.run(process_one_lesson_audio(database, settings)) is True

    status_response = client.get(audio_status_path(), headers=auth_headers(settings, user.apple_sub))
    assert status_response.json()["status"] == "ready"
    download = client.get(
        f"/me/lesson-sessions/{LESSON_ID}/audio?expected_content_hash={expected_hash}",
        headers=auth_headers(settings, user.apple_sub),
    )
    assert download.status_code == 200
    assert download.content == wav
    assert download.headers["x-lesson-audio-content-hash"] == expected_hash
    assert download.headers["etag"] == f'"{expected_hash}"'

    not_modified = client.get(
        f"/me/lesson-sessions/{LESSON_ID}/audio",
        headers={**auth_headers(settings, user.apple_sub), "If-None-Match": f'"{expected_hash}"'},
    )
    assert not_modified.status_code == 304


def test_expired_running_lease_is_reclaimed(tmp_path: Path):
    _, database, _ = make_client(tmp_path)
    user = database.find_or_create_user("audio-user", None)
    seed_job(database, user.id)
    first = database.claim_lesson_audio_job(lease_seconds=60)
    assert first is not None and first.attempt_count == 1
    with database._connect() as connection:
        connection.execute(
            "UPDATE lesson_audio_jobs SET lease_expires_at = '2000-01-01T00:00:00Z' WHERE id = ?",
            (first.id,),
        )
        connection.commit()
    reclaimed = database.claim_lesson_audio_job(lease_seconds=60)
    assert reclaimed is not None
    assert reclaimed.id == first.id
    assert reclaimed.attempt_count == 2


def test_retry_is_bounded_and_uses_safe_error(tmp_path: Path, monkeypatch):
    _, database, settings = make_client(tmp_path, lesson_audio_max_attempts=2)
    user = database.find_or_create_user("audio-user", None)
    seed_job(database, user.id)

    async def timeout(*_args, **_kwargs):
        raise TimeoutError("secret provider body must not persist")

    monkeypatch.setattr("app.lesson_audio_worker.generate_wav", timeout)
    assert asyncio.run(process_one_lesson_audio(database, settings)) is True
    with database._connect() as connection:
        connection.execute("UPDATE lesson_audio_jobs SET next_attempt_at = '2000-01-01T00:00:00Z'")
        connection.commit()
    assert asyncio.run(process_one_lesson_audio(database, settings)) is True

    _, _, job = database.lesson_audio_status(user_id=user.id, lesson_id=LESSON_ID)
    assert job is not None
    assert job.status == "failed"
    assert job.attempt_count == 2
    assert job.last_error_code == "provider_timeout"
    assert "secret" not in (job.last_error_summary or "")


def test_regeneration_supersedes_running_job_and_rejects_late_result(tmp_path: Path):
    _, database, _ = make_client(tmp_path)
    user = database.find_or_create_user("audio-user", None)
    session = database.upsert_lesson_session(
        user_id=user.id, lesson_id=LESSON_ID, state=lesson_state(), generated_lesson=generated_lesson(),
        messages=[], chat_summary=None, client_updated_at="2026-08-20T10:00:00Z",
        base_server_updated_at=None, reset_generation=False,
    )
    database.request_lesson_audio_job(
        user_id=user.id, lesson_id=LESSON_ID, max_queued_per_user=5, retry_cooldown_seconds=0,
    )
    old_job = database.claim_lesson_audio_job(lease_seconds=60)
    assert old_job is not None

    replacement = generated_lesson()
    replacement["dialogue"][0]["text"] = "Ett helt nytt innehåll"
    database.upsert_lesson_session(
        user_id=user.id, lesson_id=LESSON_ID, state=lesson_state(), generated_lesson=replacement,
        messages=[], chat_summary=None, client_updated_at="2026-08-20T10:01:00Z",
        base_server_updated_at=session.server_updated_at, reset_generation=True,
    )

    assert database.complete_lesson_audio_job(job=old_job, audio_data=valid_wav()) is False
    assert database.get_lesson_audio(user_id=user.id, lesson_id=LESSON_ID) is None
    with database._connect() as connection:
        status = connection.execute("SELECT status FROM lesson_audio_jobs WHERE id = ?", (old_job.id,)).fetchone()[0]
    assert status == "superseded"


def test_pruning_keeps_audio_for_active_incomplete_lessons(tmp_path: Path):
    _, database, _ = make_client(tmp_path)
    user = database.find_or_create_user("audio-user", None)
    for day in range(1, 7):
        lesson_id = f"b1_stage_1_week_1_day_{day}"
        state = {**lesson_state(), "lesson_id": lesson_id}
        lesson = generated_lesson()
        lesson["lesson_id"] = lesson_id
        database.upsert_lesson_session(
            user_id=user.id, lesson_id=lesson_id, state=state, generated_lesson=lesson,
            messages=[], chat_summary=None, client_updated_at=f"2026-08-2{day}T10:00:00Z",
            base_server_updated_at=None, reset_generation=False,
        )
        assert database.store_lesson_audio(
            user_id=user.id, lesson_id=lesson_id, audio_data=valid_wav(),
        ) is not None

    with database._connect() as connection:
        retained = connection.execute(
            "SELECT COUNT(*) FROM lesson_audio_cache WHERE user_id = ?", (user.id,)
        ).fetchone()[0]
    assert retained == 6


def test_queue_cap_limits_distinct_active_jobs_per_user(tmp_path: Path):
    _, database, _ = make_client(tmp_path)
    user = database.find_or_create_user("audio-user", None)
    for day in (1, 2):
        lesson_id = f"b1_stage_1_week_1_day_{day}"
        state = {**lesson_state(), "lesson_id": lesson_id}
        lesson = generated_lesson()
        lesson["lesson_id"] = lesson_id
        database.upsert_lesson_session(
            user_id=user.id, lesson_id=lesson_id, state=state, generated_lesson=lesson,
            messages=[], chat_summary=None, client_updated_at="2026-08-20T10:00:00Z",
            base_server_updated_at=None, reset_generation=False,
        )

    database.request_lesson_audio_job(
        user_id=user.id, lesson_id="b1_stage_1_week_1_day_1",
        max_queued_per_user=1, retry_cooldown_seconds=0,
    )
    try:
        database.request_lesson_audio_job(
            user_id=user.id, lesson_id="b1_stage_1_week_1_day_2",
            max_queued_per_user=1, retry_cooldown_seconds=0,
        )
    except OverflowError:
        pass
    else:
        raise AssertionError("Expected per-user queue cap to reject a distinct active job.")


def make_client(tmp_path: Path, **overrides):
    settings = Settings(
        openai_api_key="test-openai",
        gemini_api_key="test-gemini",
        app_jwt_secret="test-secret",
        apple_client_id="test-client",
        database_path=tmp_path / "svenska.db",
        **overrides,
    )
    database = Database(settings.database_path)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_database] = lambda: database
    return TestClient(app), database, settings


def auth_headers(settings: Settings, apple_sub: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_session_token(apple_sub, settings)}"}


def store_generated_session(client: TestClient, settings: Settings, apple_sub: str):
    response = client.put(
        f"/me/lesson-sessions/{LESSON_ID}",
        headers=auth_headers(settings, apple_sub),
        json={
            "state": lesson_state(),
            "generated_lesson": generated_lesson(),
            "messages": [],
            "client_updated_at": "2026-08-20T10:00:00Z",
        },
    )
    assert response.status_code == 200
    return response


def seed_job(database: Database, user_id: int):
    database.upsert_lesson_session(
        user_id=user_id, lesson_id=LESSON_ID, state=lesson_state(), generated_lesson=generated_lesson(),
        messages=[], chat_summary=None, client_updated_at="2026-08-20T10:00:00Z",
        base_server_updated_at=None, reset_generation=False,
    )
    return database.request_lesson_audio_job(
        user_id=user_id, lesson_id=LESSON_ID, max_queued_per_user=5, retry_cooldown_seconds=0,
    )


def lesson_state() -> dict:
    return {
        "lesson_id": LESSON_ID,
        "phase": "generated",
        "is_completed": False,
        "updated_at": "2026-08-20T10:00:00Z",
    }


def generated_lesson() -> dict:
    return {
        "lesson_id": LESSON_ID,
        "dialogue": [
            {"speaker": "Anna", "text": "Hej, hur är läget?"},
            {"speaker": "Erik", "text": "Det är bra, tack."},
            *[
                {"speaker": "Anna" if index % 2 == 0 else "Erik", "text": f"Test line {index + 1}."}
                for index in range(2, 20)
            ],
        ],
        "comprehension_questions": [],
        "generated_at": "2026-08-20T10:00:00Z",
        "model": "test-model",
        "schema_version": 1,
    }


def valid_wav() -> bytes:
    return b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"fmt " + b"\x00" * 32


def audio_generate_path() -> str:
    return f"/me/lesson-sessions/{LESSON_ID}/audio/generate"


def audio_status_path() -> str:
    return f"/me/lesson-sessions/{LESSON_ID}/audio/status"
