from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app import main, openai_client
from app.auth import get_database, get_settings, issue_session_token
from app.config import Settings
from app.db import Database
from app.learning_catalog import LearningCatalog, grammar_code, vocabulary_target_key
from app.learning_service import select_practice_targets
from app.main import app


def test_catalog_loads_both_levels_and_stable_target_types():
    catalog = LearningCatalog.load()

    assert len(catalog.lessons) == 224
    assert catalog.lessons[0].course_level == "B1"
    assert catalog.lessons[-1].course_level == "B2"
    assert vocabulary_target_key("word", " Hej ") == "vocabulary:word:hej"
    assert vocabulary_target_key("expression", "Hej") == "vocabulary:expression:hej"
    assert grammar_code("Ordföljd i bisats") == "grammar:ordfoljd-i-bisats"


def test_selector_reports_current_user_stage_and_excludes_future_lessons(tmp_path):
    database, user = make_database(tmp_path)
    catalog = LearningCatalog.load()
    first = catalog.lessons[0]
    second = catalog.lessons[1]
    mark_lesson_completed(database, user.id, first.lesson_id)

    progression, targets = select_practice_targets(database=database, catalog=catalog, user_id=user.id)

    assert progression["current_lesson_id"] == second.lesson_id
    assert progression["course_level"] == second.course_level
    assert progression["stage_number"] == second.stage_number
    assert len(targets) == 5
    assert all(
        target["lesson_id"] in {first.lesson_id, second.lesson_id}
        for target in targets
    )


def test_manually_completed_future_lesson_does_not_enter_fallback_selection(tmp_path):
    database, user = make_database(tmp_path)
    catalog = LearningCatalog.load()
    future = catalog.lessons[40]
    mark_lesson_completed(database, user.id, future.lesson_id)

    progression, targets = select_practice_targets(database=database, catalog=catalog, user_id=user.id)

    assert progression["current_lesson_id"] == catalog.lessons[0].lesson_id
    assert all(target["lesson_id"] != future.lesson_id for target in targets)


def test_practice_api_is_user_scoped_and_completes_with_evaluation_job(tmp_path, monkeypatch):
    client, database, settings = make_client(tmp_path)
    user_a = database.find_or_create_user("apple-a", None)
    user_b = database.find_or_create_user("apple-b", None)
    seen_progression = {}

    async def fake_generate(*_, **kwargs):
        seen_progression.update(kwargs["progression"])
        targets = kwargs["selected_targets"]
        return {
            "opening_text": "Nu tränar vi.",
            "questions": [
                {
                    "id": f"q{index + 1}",
                    "sentence_en": f"Sentence {index + 1}",
                    "target_keys": [target["target_key"]],
                }
                for index, target in enumerate(targets)
            ],
        }

    async def fake_message(*_, **__):
        return {
            "assistant_text": "Bra försök.",
            "turn_kind": "answer_feedback",
            "answer_assessment": "partial",
            "active_question_answered": True,
        }

    monkeypatch.setattr(main, "generate_vocabulary_quiz", fake_generate)
    monkeypatch.setattr(main, "send_vocabulary_message", fake_message)
    headers_a = auth_headers(settings, user_a.apple_sub)

    created = client.post("/me/vocabulary-practices", headers=headers_a)
    assert created.status_code == 200
    practice_id = created.json()["id"]
    assert seen_progression["stage_number"] == 1
    assert "target_keys" not in created.text

    forbidden = client.get(
        f"/me/vocabulary-practices/{practice_id}",
        headers=auth_headers(settings, user_b.apple_sub),
    )
    assert forbidden.status_code == 404

    for index in range(5):
        message = client.post(
            f"/me/vocabulary-practices/{practice_id}/messages",
            headers=headers_a,
            json={"latest_user_message": f"mitt svar {index}"},
        )
        assert message.status_code == 200
        advanced = client.post(f"/me/vocabulary-practices/{practice_id}/next", headers=headers_a)
        assert advanced.status_code == 200

    assert advanced.json()["status"] == "completed"
    with database._connect() as connection:
        jobs = connection.execute(
            "SELECT status, source_kind FROM evaluation_jobs WHERE user_id = ?",
            (user_a.id,),
        ).fetchall()
    assert [(row["status"], row["source_kind"]) for row in jobs] == [
        ("pending", "vocabulary_practice")
    ]


def test_next_requires_an_assessed_answer(tmp_path, monkeypatch):
    client, database, settings = make_client(tmp_path)
    user = database.find_or_create_user("apple-a", None)

    async def fake_generate(*_, **kwargs):
        targets = kwargs["selected_targets"]
        return {
            "opening_text": "Start.",
            "questions": [
                {"id": f"q{i + 1}", "sentence_en": f"Sentence {i + 1}", "target_keys": [target["target_key"]]}
                for i, target in enumerate(targets)
            ],
        }

    monkeypatch.setattr(main, "generate_vocabulary_quiz", fake_generate)
    created = client.post("/me/vocabulary-practices", headers=auth_headers(settings, user.apple_sub))
    response = client.post(
        f"/me/vocabulary-practices/{created.json()['id']}/next",
        headers=auth_headers(settings, user.apple_sub),
    )

    assert response.status_code == 409


def test_mastery_requires_two_independent_demonstrations_and_reactivates(tmp_path):
    database, user = make_database(tmp_path)
    candidate = {
        "target_kind": "vocabulary",
        "target_key": "vocabulary:word:hej",
        "display_text": "hej",
        "target_subtype": "word",
        "source_level": "B1",
    }

    apply_result(database, user.id, "session-1", candidate, "struggled")
    target = database.list_active_learning_targets(user_id=user.id)[0]
    assert target["status"] == "active"

    apply_result(database, user.id, "session-2", candidate, "demonstrated")
    target = database.list_active_learning_targets(user_id=user.id)[0]
    assert target["success_streak"] == 1

    apply_result(database, user.id, "session-3", candidate, "demonstrated")
    assert database.list_active_learning_targets(user_id=user.id) == []
    resolved = database.learning_target_states(user_id=user.id, target_keys=[candidate["target_key"]])
    assert resolved[candidate["target_key"]]["status"] == "resolved"

    apply_result(database, user.id, "session-4", candidate, "struggled")
    reactivated = database.list_active_learning_targets(user_id=user.id)[0]
    assert reactivated["status"] == "active"
    assert reactivated["success_streak"] == 0


def test_vocabulary_interactor_receives_stage_in_stable_input_order(monkeypatch):
    captured = {}

    async def fake_send(*_, **kwargs):
        captured.update(kwargs)
        return {"questions": [], "opening_text": ""}

    monkeypatch.setattr(openai_client, "send_structured_request", fake_send)
    asyncio.run(
        openai_client.generate_vocabulary_quiz(
            sample_settings(),
            practice_id="practice-1",
            progression={
                "course_level": "B2",
                "stage_number": 3,
                "current_lesson_id": "b2_stage_3_week_1_day_1",
                "progress_cutoff_absolute_day": 57,
            },
            selected_targets=[],
            model="gpt-test",
            reasoning_effort="low",
        )
    )

    titles = [item["content"].split(":\n", 1)[0] for item in captured["input_value"]]
    assert titles == [
        "course_and_progression_context_json",
        "selected_target_definitions_json",
        "generation_action",
    ]
    assert '"stage_number":3' in captured["input_value"][0]["content"]
    assert "You operate within Svenska" in captured["instructions"]
    assert "Vocabulary Interactor" in captured["instructions"]
    assert captured["prompt_cache_key"] == openai_client.scoped_prompt_cache_key(
        openai_client.VOCABULARY_INTERACTOR_PROMPT_CACHE_KEY,
        "practice-1",
    )


def test_vocabulary_message_uses_stable_input_order_and_scoped_cache_key(monkeypatch):
    captured = {}

    async def fake_send(*_, **kwargs):
        captured.update(kwargs)
        return {
            "assistant_text": "Bra.",
            "turn_kind": "answer_feedback",
            "answer_assessment": "correct",
            "active_question_answered": True,
        }

    monkeypatch.setattr(openai_client, "send_structured_request", fake_send)
    asyncio.run(
        openai_client.send_vocabulary_message(
            sample_settings(),
            practice_id="practice-1",
            context={
                "progression": {
                    "course_level": "B2",
                    "stage_number": 3,
                    "current_lesson_id": "b2_stage_3_week_1_day_1",
                },
                "selected_targets": [{"target_key": "vocabulary:word:hej"}],
                "quiz": {
                    "questions": [
                        {
                            "id": "q1",
                            "sentence_en": "Hello.",
                            "target_keys": ["vocabulary:word:hej"],
                        }
                    ]
                },
                "prior_messages": [{"role": "assistant", "content": "Nu börjar vi."}],
                "active_question": {
                    "id": "q1",
                    "sentence_en": "Hello.",
                    "target_keys": ["vocabulary:word:hej"],
                },
                "practice_state": {"current_question_index": 0, "answered_question_ids": []},
            },
            latest_user_message="Hej.",
            model="gpt-test",
            reasoning_effort="low",
        )
    )

    titles = [item["content"].split(":\n", 1)[0] for item in captured["input_value"]]
    assert titles == [
        "course_and_progression_context_json",
        "selected_target_definitions_json",
        "full_quiz_metadata_json",
        "prior_practice_chat_history_json",
        "active_question_json",
        "practice_state_json",
        "latest_user_message",
    ]
    assert captured["prompt_cache_key"] == openai_client.scoped_prompt_cache_key(
        openai_client.VOCABULARY_INTERACTOR_PROMPT_CACHE_KEY,
        "practice-1",
    )


def apply_result(
    database: Database,
    user_id: int,
    source_id: str,
    candidate: dict,
    outcome: str,
) -> None:
    snapshot = {
        "evaluation_version": "v1",
        "source_kind": "lesson",
        "source_id": source_id,
        "candidates": [candidate],
        "turns": [{"turn_id": "turn_1", "role": "user", "content": "hej"}],
        "has_meaningful_evidence": True,
    }
    with database._connect() as connection:
        database._enqueue_evaluation_job(
            connection,
            user_id=user_id,
            source_kind="lesson",
            source_id=source_id,
            snapshot=snapshot,
            prompt_version="evaluator_v1",
        )
        connection.commit()
    job = database.claim_evaluation_job()
    assert job is not None
    result = {
        "target_kind": "vocabulary",
        "target_key": candidate["target_key"],
        "outcome": outcome,
        "evidence_strength": "production",
        "confidence": 0.95,
        "evidence_turn_ids": ["turn_1"],
        "reason": "Fixture evidence.",
    }
    database.apply_evaluation_results(
        job=job,
        model="gpt-test",
        raw_output={"evaluation_version": "v1", "results": [result]},
        results=[result],
    )


def mark_lesson_completed(database: Database, user_id: int, lesson_id: str) -> None:
    database.upsert_lesson_session(
        user_id=user_id,
        lesson_id=lesson_id,
        state={"lesson_id": lesson_id, "phase": "completed", "is_completed": True},
        generated_lesson=None,
        messages=[],
        chat_summary=None,
        client_updated_at="2026-06-21T00:00:00Z",
        base_server_updated_at=None,
        reset_generation=False,
    )


def make_database(tmp_path: Path):
    database = Database(tmp_path / "svenska.db")
    return database, database.find_or_create_user("apple-user", None)


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


def sample_settings() -> Settings:
    return Settings(
        openai_api_key="test-openai",
        gemini_api_key="test-gemini",
        app_jwt_secret="test-secret",
        apple_client_id="test-client",
        database_path=Path("/tmp/test-svenska.db"),
    )


def auth_headers(settings: Settings, apple_sub: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_session_token(apple_sub, settings)}"}
