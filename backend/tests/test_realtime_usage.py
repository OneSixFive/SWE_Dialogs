import asyncio
from pathlib import Path

from app import main
from app.config import Settings
from app.db import Database
from app.realtime_usage import (
    RealtimeUsageError,
    build_speaking_usage_event,
    estimated_realtime_cost_metrics,
    normalize_realtime_response_done,
)


def test_normalizes_mixed_realtime_usage_and_drops_unknown_fields():
    normalized = normalize_realtime_response_done(
        response_done_event(
            input_tokens=100,
            text_input=40,
            audio_input=50,
            image_input=10,
            cached_text=20,
            cached_audio=10,
            cached_image=5,
            text_output=10,
            audio_output=15,
            reasoning_output=5,
            extra={"transcript": "must not persist", "future_field": {"value": 1}},
        )
    )

    assert normalized is not None
    assert normalized.response_id == "resp_usage_1"
    assert normalized.usage == {
        "total_tokens": 130,
        "input_tokens": 100,
        "output_tokens": 30,
        "input_token_details": {
            "text_tokens": 40,
            "audio_tokens": 50,
            "image_tokens": 10,
            "cached_tokens": 35,
            "cached_tokens_details": {
                "text_tokens": 20,
                "audio_tokens": 10,
                "image_tokens": 5,
            },
        },
        "output_token_details": {
            "text_tokens": 10,
            "audio_tokens": 15,
            "reasoning_tokens": 5,
        },
    }
    assert "transcript" not in str(normalized.usage)


def test_normalizer_ignores_unrelated_events_and_accepts_zero_usage():
    assert normalize_realtime_response_done({"type": "response.created"}) is None
    normalized = normalize_realtime_response_done(
        {
            "type": "response.done",
            "response": {
                "id": "resp_zero",
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            },
        }
    )
    assert normalized is not None
    assert normalized.usage["input_token_details"]["cached_tokens"] == 0


def test_normalizer_rejects_missing_or_inconsistent_usage():
    inconsistent_output = response_done_event(text_output=11)
    inconsistent_output["response"]["usage"]["output_tokens"] = 30
    inconsistent_output["response"]["usage"]["total_tokens"] = 130
    invalid_events = [
        {"type": "response.done", "response": {"id": "resp_missing"}},
        response_done_event(input_tokens=-1),
        response_done_event(input_tokens=True),
        response_done_event(input_tokens=101),
        response_done_event(cached_text=41),
        inconsistent_output,
    ]

    for event in invalid_events:
        try:
            normalize_realtime_response_done(event)
        except RealtimeUsageError:
            pass
        else:
            raise AssertionError(f"Expected invalid event to be rejected: {event}")


def test_modality_aware_costs_include_cached_input_and_reasoning_output(tmp_path):
    settings = make_settings(tmp_path, prices=pricing())
    normalized = normalize_realtime_response_done(
        response_done_event(
            input_tokens=100,
            text_input=40,
            audio_input=50,
            image_input=10,
            cached_text=20,
            cached_audio=10,
            cached_image=5,
            text_output=10,
            audio_output=15,
            reasoning_output=5,
        )
    )
    assert normalized is not None

    costs, missing = estimated_realtime_cost_metrics(settings, "gpt-realtime-2.1", normalized.usage)

    assert missing == ()
    assert costs == {
        "estimated_cost_usd": 0.001626,
        "effective_input_cost_usd": 0.000876,
        "uncached_input_cost_usd": 0.00112,
        "net_cache_savings_usd": 0.000244,
    }


def test_missing_price_records_no_partial_cost(tmp_path):
    prices = pricing()
    prices["gpt-realtime-2.1"].pop("audio_cached_input_per_million")
    settings = make_settings(tmp_path, prices=prices)
    normalized = normalize_realtime_response_done(
        response_done_event(cached_audio=5, audio_input=50, text_input=40, image_input=10)
    )
    assert normalized is not None

    costs, missing = estimated_realtime_cost_metrics(settings, "gpt-realtime-2.1", normalized.usage)

    assert missing == ("audio_cached_input_per_million",)
    assert all(value is None for value in costs.values())


def test_cached_only_modality_still_requires_uncached_rate_for_savings(tmp_path):
    prices = pricing()
    prices["gpt-realtime-2.1"].pop("text_input_per_million")
    settings = make_settings(tmp_path, prices=prices)
    normalized = normalize_realtime_response_done(
        response_done_event(
            input_tokens=40,
            text_input=40,
            audio_input=0,
            image_input=0,
            cached_text=40,
            cached_audio=0,
            cached_image=0,
            text_output=0,
            audio_output=0,
            reasoning_output=0,
        )
    )
    assert normalized is not None

    _, missing = estimated_realtime_cost_metrics(settings, "gpt-realtime-2.1", normalized.usage)

    assert missing == ("text_input_per_million",)


def test_database_provider_response_id_is_idempotent_and_dashboard_visible(tmp_path):
    settings = make_settings(tmp_path, prices=pricing())
    database = Database(settings.database_path)
    user = database.find_or_create_user("apple-speaking-usage", "speaker@example.com")
    normalized = normalize_realtime_response_done(response_done_event())
    assert normalized is not None
    event, missing = build_speaking_usage_event(
        settings,
        user_id=user.id,
        lesson_id="b1_stage_1_week_1_day_1",
        normalized=normalized,
    )

    assert missing == ()
    assert database.record_openai_usage(event) is True
    assert database.record_openai_usage(event) is False
    summary = database.usage_dashboard_summary(
        start_time="2000-01-01T00:00:00.000000Z",
        end_time="2100-01-01T00:00:00.000000Z",
        roles=["Speaking"],
    )

    assert summary.totals["request_count"] == 1
    assert summary.role_totals[0]["request_role"] == "Speaking"
    assert summary.events[0]["source_id"] == "b1_stage_1_week_1_day_1"
    with database._connect() as connection:
        row = connection.execute(
            "SELECT provider_response_id, raw_usage_json FROM openai_usage_events"
        ).fetchone()
    assert row["provider_response_id"] == "resp_usage_1"
    assert "transcript" not in row["raw_usage_json"]


def test_usage_dashboard_exposes_speaking_role(tmp_path, monkeypatch):
    settings = make_settings(tmp_path, prices=pricing())
    database = Database(settings.database_path)

    async def fake_actual_cost(*_):
        return None

    monkeypatch.setattr(main, "_openai_org_actual_cost_usd", fake_actual_cost)
    payload = asyncio.run(
        main.usage_dashboard_data(
            start=None,
            end=None,
            role=[],
            _=None,
            database=database,
            settings=settings,
        )
    )

    assert "Speaking" in payload["available_roles"]


def response_done_event(
    *,
    input_tokens=100,
    text_input=40,
    audio_input=50,
    image_input=10,
    cached_text=20,
    cached_audio=10,
    cached_image=5,
    text_output=10,
    audio_output=15,
    reasoning_output=5,
    extra=None,
):
    cached_tokens = cached_text + cached_audio + cached_image
    output_tokens = text_output + audio_output + reasoning_output
    usage = {
        "total_tokens": input_tokens + output_tokens if isinstance(input_tokens, int) else 130,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_token_details": {
            "text_tokens": text_input,
            "audio_tokens": audio_input,
            "image_tokens": image_input,
            "cached_tokens": cached_tokens,
            "cached_tokens_details": {
                "text_tokens": cached_text,
                "audio_tokens": cached_audio,
                "image_tokens": cached_image,
            },
        },
        "output_token_details": {
            "text_tokens": text_output,
            "audio_tokens": audio_output,
            "reasoning_tokens": reasoning_output,
        },
    }
    if extra:
        usage.update(extra)
    return {"type": "response.done", "response": {"id": "resp_usage_1", "usage": usage}}


def pricing():
    return {
        "gpt-realtime-2.1": {
            "text_input_per_million": 2.0,
            "text_cached_input_per_million": 0.2,
            "text_output_per_million": 10.0,
            "audio_input_per_million": 20.0,
            "audio_cached_input_per_million": 1.0,
            "audio_output_per_million": 40.0,
            "image_input_per_million": 4.0,
            "image_cached_input_per_million": 0.4,
        }
    }


def make_settings(tmp_path: Path, *, prices):
    return Settings(
        openai_api_key="test-openai",
        gemini_api_key="test-gemini",
        app_jwt_secret="test-secret",
        apple_client_id="test-client",
        database_path=tmp_path / "svenska.db",
        openai_usage_price_overrides=prices,
    )
