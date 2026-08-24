from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app import openai_client
from app.config import Settings
from app.db import Database
from app.learning_service import validate_evaluator_output
from app.openai_client import (
    evaluator_candidate_projection,
    evaluator_schema,
    evaluator_user_state_projection,
    json_string,
)


def test_evaluate_learning_snapshot_sends_v3_schema_and_slim_inputs(monkeypatch):
    captured = {}

    async def fake_send(*_, **kwargs):
        captured.update(kwargs)
        return {"evaluation_version": "v3", "checked_target_keys": [], "updates": []}

    monkeypatch.setattr(openai_client, "send_structured_request", fake_send)
    candidate = {
        **_candidate("hej"),
        "lesson_id": "b1_stage_1_week_1_day_1",
        "stage_number": 1,
        "absolute_day": 1,
    }
    snapshot = {
        "evaluation_version": "v3",
        "source_kind": "lesson",
        "source_id": "lesson-1",
        "candidates": [candidate],
        "current_user_state": {
            candidate["target_key"]: {
                "status": "active",
                "success_streak": 1,
                "priority_score": 3.0,
            }
        },
        "source_context": {},
        "turns": [],
    }

    asyncio.run(
        openai_client.evaluate_learning_snapshot(
            _settings(),
            source_id="lesson-1",
            snapshot=snapshot,
            model="gpt-5.6-sol",
            reasoning_effort="medium",
        )
    )

    input_items = {
        openai_client._input_item_text(item).split(":\n", 1)[0]: json.loads(
            openai_client._input_item_text(item).split(":\n", 1)[1]
        )
        for item in captured["input_value"]
    }
    assert input_items["candidate_target_catalog_json"] == evaluator_candidate_projection(snapshot)
    assert input_items["current_user_state_json"] == evaluator_user_state_projection(snapshot)
    assert captured["schema"]["schema"]["required"] == [
        "evaluation_version",
        "checked_target_keys",
        "updates",
    ]
    assert captured["prompt_cache_key"] == "svenska_learning_evaluator_v3"
    assert captured["prompt_version"] == "evaluator_v3"


def test_evaluator_v3_uses_slim_candidate_and_user_state_projections():
    candidate = {
        "target_kind": "vocabulary",
        "target_key": "vocabulary:word:hej",
        "display_text": "hej",
        "description": "A greeting.",
        "target_subtype": "word",
        "source_level": "B1",
        "lesson_id": "b1_stage_1_week_1_day_1",
        "stage_number": 1,
        "absolute_day": 1,
    }
    snapshot = {
        "candidates": [candidate],
        "current_user_state": {
            candidate["target_key"]: {
                "id": 42,
                "target_kind": "vocabulary",
                "target_key": candidate["target_key"],
                "display_text": "hej",
                "target_subtype": "word",
                "source_level": "B1",
                "status": "active",
                "priority_score": 3.0,
                "success_streak": 1,
                "struggle_count": 2,
                "evidence_count": 4,
            }
        },
    }

    candidate_projection = evaluator_candidate_projection(snapshot)
    state_projection = evaluator_user_state_projection(snapshot)

    assert candidate_projection == [
        {
            "target_key": candidate["target_key"],
            "target_kind": "vocabulary",
            "display_text": "hej",
            "description": "A greeting.",
        }
    ]
    assert state_projection == {
        candidate["target_key"]: {"status": "active", "success_streak": 1}
    }
    assert len(json_string(candidate_projection)) < len(json_string([candidate]))
    assert len(json_string(state_projection)) < len(json_string(snapshot["current_user_state"]))


def test_evaluator_v3_schema_uses_source_specific_evidence_ids():
    lesson_update = evaluator_schema(
        evaluation_version="v3", source_kind="lesson"
    )["schema"]["properties"]["updates"]["items"]
    lookup_update = evaluator_schema(
        evaluation_version="v3", source_kind="translation_lookup"
    )["schema"]["properties"]["updates"]["items"]

    assert "target_kind" not in lesson_update["properties"]
    assert "evidence_turn_ids" in lesson_update["properties"]
    assert "evidence_lookup_ids" not in lesson_update["properties"]
    assert lesson_update["properties"]["outcome"]["enum"] == [
        "struggled",
        "partial",
        "demonstrated",
    ]
    assert "evidence_lookup_ids" in lookup_update["properties"]
    assert "evidence_turn_ids" not in lookup_update["properties"]
    assert lookup_update["properties"]["outcome"]["enum"] == ["lookup_requested"]


def test_evaluator_v3_requires_complete_checked_keys_and_actionable_updates():
    tracked = _candidate("tracked")
    untracked = _candidate("untracked")
    snapshot = {
        "evaluation_version": "v3",
        "source_kind": "lesson",
        "candidates": [tracked, untracked],
        "current_user_state": {tracked["target_key"]: {"status": "active", "success_streak": 0}},
        "turns": [{"turn_id": "turn_1", "role": "user", "content": "hej"}],
    }
    valid_output = {
        "evaluation_version": "v3",
        "checked_target_keys": [tracked["target_key"], untracked["target_key"]],
        "updates": [
            {
                "target_key": tracked["target_key"],
                "outcome": "demonstrated",
                "evidence_strength": "production",
                "confidence": 0.9,
                "evidence_turn_ids": ["turn_1"],
                "reason": "Independent production.",
            },
            {
                "target_key": untracked["target_key"],
                "outcome": "partial",
                "evidence_strength": "production",
                "confidence": 0.8,
                "evidence_turn_ids": ["turn_1"],
                "reason": "Incomplete production.",
            },
        ],
    }

    assert validate_evaluator_output(valid_output, snapshot) == valid_output["updates"]

    incomplete = {**valid_output, "checked_target_keys": [tracked["target_key"]]}
    with pytest.raises(ValueError, match="check every supplied candidate"):
        validate_evaluator_output(incomplete, snapshot)

    duplicate = {
        **valid_output,
        "checked_target_keys": [tracked["target_key"], tracked["target_key"]],
    }
    with pytest.raises(ValueError, match="contains duplicates"):
        validate_evaluator_output(duplicate, snapshot)

    untracked_demonstration = {
        **valid_output,
        "updates": [
            {
                **valid_output["updates"][0],
                "target_key": untracked["target_key"],
            }
        ],
    }
    with pytest.raises(ValueError, match="untracked targets"):
        validate_evaluator_output(untracked_demonstration, snapshot)

    no_evidence_update = {
        **valid_output,
        "updates": [
            {
                **valid_output["updates"][1],
                "outcome": "no_evidence",
            }
        ],
    }
    with pytest.raises(ValueError, match="omit no_evidence"):
        validate_evaluator_output(no_evidence_update, snapshot)


def test_evaluator_v3_omitted_candidates_do_not_create_learning_state(tmp_path: Path):
    database = Database(tmp_path / "svenska.db")
    user = database.find_or_create_user("apple-user", None)
    partial = _candidate("partial")
    omitted = _candidate("omitted")
    snapshot = {
        "evaluation_version": "v3",
        "source_kind": "lesson",
        "source_id": "lesson-1",
        "candidates": [partial, omitted],
        "turns": [{"turn_id": "turn_1", "role": "user", "content": "fixture"}],
        "has_meaningful_evidence": True,
    }
    with database._connect() as connection:
        database._enqueue_evaluation_job(
            connection,
            user_id=user.id,
            source_kind="lesson",
            source_id="lesson-1",
            snapshot=snapshot,
            prompt_version="evaluator_v3",
        )
        connection.commit()
    job = database.claim_evaluation_job()
    assert job is not None
    output = {
        "evaluation_version": "v3",
        "checked_target_keys": [partial["target_key"], omitted["target_key"]],
        "updates": [
            {
                "target_key": partial["target_key"],
                "outcome": "partial",
                "evidence_strength": "production",
                "confidence": 0.9,
                "evidence_turn_ids": ["turn_1"],
                "reason": "Partial fixture evidence.",
            }
        ],
    }
    updates = validate_evaluator_output(output, job.input_snapshot)

    database.apply_evaluation_results(
        job=job,
        model="gpt-test",
        raw_output=output,
        results=updates,
    )

    states = database.learning_target_states(
        user_id=user.id,
        target_keys=[partial["target_key"], omitted["target_key"]],
    )
    assert set(states) == {partial["target_key"]}
    assert states[partial["target_key"]]["status"] == "active"


def test_legacy_evaluator_output_remains_supported():
    candidate = _candidate("legacy")
    snapshot = {
        "evaluation_version": "v2",
        "source_kind": "lesson",
        "candidates": [candidate],
        "turns": [],
    }
    output = {
        "evaluation_version": "v2",
        "results": [
            {
                "target_kind": candidate["target_kind"],
                "target_key": candidate["target_key"],
                "outcome": "no_evidence",
                "evidence_strength": "recognition",
                "confidence": 0.5,
                "evidence_turn_ids": [],
                "evidence_lookup_ids": [],
                "reason": "No evidence.",
            }
        ],
    }

    assert validate_evaluator_output(output, snapshot) == output["results"]
    assert evaluator_schema(evaluation_version="v2")["schema"]["required"] == [
        "evaluation_version",
        "results",
    ]


def _candidate(suffix: str) -> dict[str, object]:
    return {
        "target_kind": "vocabulary",
        "target_key": f"vocabulary:word:{suffix}",
        "display_text": suffix,
        "description": f"Fixture target {suffix}.",
        "target_subtype": "word",
        "source_level": "B1",
    }


def _settings() -> Settings:
    return Settings(
        openai_api_key="test-openai",
        gemini_api_key="test-gemini",
        app_jwt_secret="test-secret",
        apple_client_id="test-client",
        database_path=Path("/tmp/test-svenska.db"),
    )
