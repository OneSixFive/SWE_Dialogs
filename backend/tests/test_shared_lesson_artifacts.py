from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import get_database, get_settings, issue_session_token
from app.config import Settings
from app.db import Database
from app.lesson_artifacts import audio_recipe, lesson_recipe
from app.lesson_audio_worker import process_one_lesson_audio
from app.learning_catalog import get_learning_catalog
from app.main import app
from app.openai_client import generator_prompt_sources


LESSON_ID = "b1_stage_1_week_1_day_1"


def test_recipe_fingerprints_change_only_with_semantic_configuration():
    settings = make_settings(Path("/tmp/unused-shared-artifact-test.db"))
    shared_prompt, generator_prompt = generator_prompt_sources()
    payload = {"id": LESSON_ID, "coursePosition": {"day": 1}}
    baseline = lesson_recipe(
        settings,
        lesson_id=LESSON_ID,
        payload=payload,
        shared_base_prompt=shared_prompt,
        generator_prompt=generator_prompt,
    )

    changed_model = lesson_recipe(
        replace(settings, lesson_generator_model="gpt-test-next"),
        lesson_id=LESSON_ID,
        payload=payload,
        shared_base_prompt=shared_prompt,
        generator_prompt=generator_prompt,
    )
    changed_prompt = lesson_recipe(
        settings,
        lesson_id=LESSON_ID,
        payload=payload,
        shared_base_prompt=shared_prompt + "\nsemantic change",
        generator_prompt=generator_prompt,
    )
    changed_payload = lesson_recipe(
        settings,
        lesson_id=LESSON_ID,
        payload={**payload, "lessonIntent": {"goal": "changed"}},
        shared_base_prompt=shared_prompt,
        generator_prompt=generator_prompt,
    )

    assert changed_model.fingerprint != baseline.fingerprint
    assert changed_prompt.fingerprint != baseline.fingerprint
    assert changed_payload.fingerprint != baseline.fingerprint
    assert audio_recipe(replace(settings, lesson_tts_recipe_version="tts-next")).fingerprint != audio_recipe(
        settings
    ).fingerprint


def test_second_user_reuses_shared_artifact_without_provider_call(tmp_path: Path, monkeypatch):
    client, database, settings = make_client(tmp_path)
    user_a = database.find_or_create_user("artifact-a", None)
    user_b = database.find_or_create_user("artifact-b", None)
    provider_calls = 0

    async def fake_generate(*_args, **kwargs):
        nonlocal provider_calls
        provider_calls += 1
        recorder = kwargs.get("response_metadata_recorder")
        if recorder is not None:
            recorder({"provider_model": "provider-model", "provider_request_id": "request-1"})
        return generated_lesson()

    monkeypatch.setattr("app.main.generate_lesson", fake_generate)
    first = resolve(client, settings, user_a.apple_sub)
    second = resolve(client, settings, user_b.apple_sub)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["resolution"] == "generated"
    assert second.json()["resolution"] == "cache_hit"
    assert first.json()["artifact"] == second.json()["artifact"]
    assert provider_calls == 1
    with database._connect() as connection:
        row = connection.execute(
            "SELECT provider_model, provider_request_id FROM lesson_artifacts"
        ).fetchone()
    assert tuple(row) == ("provider-model", "request-1")


def test_private_regeneration_is_owner_scoped_and_does_not_replace_shared(tmp_path: Path, monkeypatch):
    client, database, settings = make_client(tmp_path)
    user_a = database.find_or_create_user("artifact-a", None)
    user_b = database.find_or_create_user("artifact-b", None)
    generation_number = 0

    async def fake_generate(*_args, **_kwargs):
        nonlocal generation_number
        generation_number += 1
        lesson = generated_lesson()
        lesson["dialogue"][0]["text"] = f"Generation {generation_number}"
        return lesson

    monkeypatch.setattr("app.main.generate_lesson", fake_generate)
    shared = resolve(client, settings, user_a.apple_sub).json()["artifact"]
    private = resolve(client, settings, user_b.apple_sub, mode="private").json()["artifact"]
    shared_again = resolve(client, settings, user_a.apple_sub).json()["artifact"]

    assert private["scope"] == "private"
    assert private["id"] != shared["id"]
    assert shared_again == shared
    assert generation_number == 2

    forbidden = client.put(
        f"/me/lesson-sessions/{LESSON_ID}",
        headers=auth_headers(settings, user_a.apple_sub),
        json=session_payload(private),
    )
    assert forbidden.status_code == 403


def test_session_regeneration_reclaims_interrupted_operation_and_finalizes_once(
    tmp_path: Path, monkeypatch
):
    client, database, settings = make_client(tmp_path)
    user = database.find_or_create_user("artifact-regeneration", None)

    async def fake_initial(*_args, **_kwargs):
        return generated_lesson()

    monkeypatch.setattr("app.main.generate_lesson", fake_initial)
    shared = resolve(client, settings, user.apple_sub).json()["artifact"]
    stored = client.put(
        f"/me/lesson-sessions/{LESSON_ID}",
        headers=auth_headers(settings, user.apple_sub),
        json=session_payload(shared),
    )
    assert stored.status_code == 200
    base_server_updated_at = stored.json()["server_updated_at"]

    shared_prompt, generator_prompt = generator_prompt_sources()
    catalog_lesson = get_learning_catalog().lesson(LESSON_ID)
    assert catalog_lesson is not None
    recipe = lesson_recipe(
        settings,
        lesson_id=LESSON_ID,
        payload=catalog_lesson.payload,
        shared_base_prompt=shared_prompt,
        generator_prompt=generator_prompt,
    )
    operation_key = "regeneration-operation-1234"
    interrupted, claimed = database.begin_lesson_generation(
        lesson_id=LESSON_ID,
        recipe_fingerprint=recipe.fingerprint,
        recipe=recipe.document,
        scope="private",
        requested_by_user_id=user.id,
        lease_seconds=300,
        operation_key=operation_key,
        expected_server_updated_at=base_server_updated_at,
    )
    assert claimed is True
    with database._connect() as connection:
        connection.execute(
            "UPDATE lesson_generation_jobs SET lease_expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00.000000Z", interrupted.id),
        )
        connection.commit()

    provider_calls = 0

    async def fake_regeneration(*_args, **_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        lesson = generated_lesson()
        lesson["dialogue"][0]["text"] = "Private replacement"
        return lesson

    monkeypatch.setattr("app.main.generate_lesson", fake_regeneration)
    request = {
        "operation_key": operation_key,
        "base_server_updated_at": base_server_updated_at,
    }
    first = client.post(
        f"/me/lesson-sessions/{LESSON_ID}/regenerate",
        headers=auth_headers(settings, user.apple_sub),
        json=request,
    )
    replay = client.post(
        f"/me/lesson-sessions/{LESSON_ID}/regenerate",
        headers=auth_headers(settings, user.apple_sub),
        json=request,
    )

    assert first.status_code == replay.status_code == 200
    assert first.json()["artifact"] == replay.json()["artifact"]
    assert first.json()["session"]["lesson_artifact_id"] == first.json()["artifact"]["id"]
    assert first.json()["session"]["state"]["phase"] == "generated"
    assert first.json()["session"]["messages"] == []
    assert first.json()["audio"]["status"] == "pending"
    assert provider_calls == 1
    with database._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM lesson_generation_jobs WHERE operation_key = ?",
            (operation_key,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM lesson_artifacts WHERE scope = 'private'"
        ).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM artifact_audio_jobs").fetchone()[0] == 1


def test_invalidated_shared_artifact_is_replaced_but_existing_pin_remains_valid(
    tmp_path: Path, monkeypatch
):
    client, database, settings = make_client(tmp_path)
    user_a = database.find_or_create_user("artifact-a", None)
    user_b = database.find_or_create_user("artifact-b", None)
    generation_number = 0

    async def fake_generate(*_args, **_kwargs):
        nonlocal generation_number
        generation_number += 1
        lesson = generated_lesson()
        lesson["dialogue"][0]["text"] = f"Generation {generation_number}"
        return lesson

    monkeypatch.setattr("app.main.generate_lesson", fake_generate)
    first = resolve(client, settings, user_a.apple_sub).json()["artifact"]
    pinned = client.put(
        f"/me/lesson-sessions/{LESSON_ID}",
        headers=auth_headers(settings, user_a.apple_sub),
        json=session_payload(first),
    )
    assert pinned.status_code == 200
    assert database.invalidate_lesson_artifact(artifact_id=first["id"], reason="test") is True

    replacement = resolve(client, settings, user_b.apple_sub).json()["artifact"]
    assert replacement["id"] != first["id"]
    assert generation_number == 2
    restored = client.get(
        f"/me/lesson-sessions/{LESSON_ID}",
        headers=auth_headers(settings, user_a.apple_sub),
    )
    assert restored.status_code == 200
    assert restored.json()["lesson_artifact_id"] == first["id"]


def test_two_users_share_one_audio_job_file_and_download(tmp_path: Path, monkeypatch):
    client, database, settings = make_client(tmp_path)
    user_a = database.find_or_create_user("artifact-a", None)
    user_b = database.find_or_create_user("artifact-b", None)

    async def fake_lesson(*_args, **_kwargs):
        return generated_lesson()

    monkeypatch.setattr("app.main.generate_lesson", fake_lesson)
    artifact = resolve(client, settings, user_a.apple_sub).json()["artifact"]
    for user in (user_a, user_b):
        stored = client.put(
            f"/me/lesson-sessions/{LESSON_ID}",
            headers=auth_headers(settings, user.apple_sub),
            json=session_payload(artifact),
        )
        assert stored.status_code == 200

    first = client.post(audio_generate_path(), headers=auth_headers(settings, user_a.apple_sub))
    second = client.post(audio_generate_path(), headers=auth_headers(settings, user_b.apple_sub))
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["content_hash"] == second.json()["content_hash"]
    with database._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifact_audio_jobs").fetchone()[0] == 1

    wav = valid_wav()

    async def fake_audio(*_args, **_kwargs):
        return wav

    monkeypatch.setattr("app.lesson_audio_worker.generate_wav", fake_audio)
    assert asyncio.run(process_one_lesson_audio(database, settings)) is True

    downloads = [
        client.get(
            f"/me/lesson-sessions/{LESSON_ID}/audio",
            headers=auth_headers(settings, user.apple_sub),
        )
        for user in (user_a, user_b)
    ]
    assert [response.status_code for response in downloads] == [200, 200]
    assert downloads[0].content == downloads[1].content == wav
    assert downloads[0].headers["etag"] == downloads[1].headers["etag"]
    with database._connect() as connection:
        audio = connection.execute(
            "SELECT relative_file_path FROM artifact_audio_cache"
        ).fetchone()
    assert (settings.shared_audio_directory / audio["relative_file_path"]).read_bytes() == wav


def make_client(tmp_path: Path) -> tuple[TestClient, Database, Settings]:
    settings = make_settings(tmp_path / "svenska.db")
    database = Database(settings.database_path)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_database] = lambda: database
    return TestClient(app), database, settings


def make_settings(database_path: Path) -> Settings:
    return Settings(
        openai_api_key="test-openai",
        gemini_api_key="test-gemini",
        app_jwt_secret="test-secret",
        apple_client_id="test-client",
        database_path=database_path,
        lesson_generator_model="gpt-test",
        shared_audio_directory=database_path.parent / "shared-audio",
    )


def auth_headers(settings: Settings, apple_sub: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_session_token(apple_sub, settings)}"}


def resolve(client: TestClient, settings: Settings, apple_sub: str, *, mode: str = "shared"):
    return client.post(
        "/lessons/artifacts/resolve",
        headers=auth_headers(settings, apple_sub),
        json={"lesson_id": LESSON_ID, "mode": mode},
    )


def session_payload(artifact: dict) -> dict:
    return {
        "lesson_artifact_id": artifact["id"],
        "state": {
            "lesson_id": LESSON_ID,
            "phase": "generated",
            "is_completed": False,
            "updated_at": "2026-08-23T20:00:00Z",
        },
        "generated_lesson": artifact["generated_lesson"],
        "messages": [],
        "client_updated_at": "2026-08-23T20:00:00Z",
    }


def generated_lesson() -> dict:
    return {
        "lesson_id": LESSON_ID,
        "dialogue": [
            {"speaker": "Anna" if index % 2 == 0 else "Erik", "text": f"Line {index + 1}"}
            for index in range(20)
        ],
        "comprehension_questions": [
            {"id": f"q{index}", "question_sv": f"Fråga {index}?"}
            for index in range(1, 4)
        ],
        "generated_at": "2026-08-23T20:00:00Z",
        "model": "gpt-test",
        "schema_version": 1,
    }


def valid_wav() -> bytes:
    return b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"fmt " + b"\x00" * 32


def audio_generate_path() -> str:
    return f"/me/lesson-sessions/{LESSON_ID}/audio/generate"
