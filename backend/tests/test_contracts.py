import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from app import openai_client
from app.config import Settings
from app.openai_client import (
    PROMPTS_DIR,
    append_only_history_input_items,
    _input_section_metrics,
    active_comprehension_questions_object,
    active_translation_sentence_object,
    build_generated_lesson,
    course_context_object,
    generated_dialogue_object,
    interactor_lesson_state_object,
    prior_chat_message_objects,
    response_input_item,
    sanitized_interactor_response,
    scoped_prompt_cache_key,
    snake_case_keys,
    validate_generated_lesson_draft,
    validate_interactor_response,
)


def test_snake_case_keys_converts_nested_payload():
    payload = {
        "coursePosition": {"absoluteDay": 1, "stageName": "Stage"},
        "lessonIntent": {"oneSentenceGoal": "Goal"},
        "activeWords": ["hej"],
    }

    assert snake_case_keys(payload) == {
        "course_position": {"absolute_day": 1, "stage_name": "Stage"},
        "lesson_intent": {"one_sentence_goal": "Goal"},
        "active_words": ["hej"],
    }


def test_course_context_from_lesson_id():
    assert course_context_object({"id": "b1_s1_w1_d1"}) == {
        "course_level": "B1",
        "explanation_swedish_level": "A2",
    }
    assert course_context_object({"id": "b2_s1_w1_d1"}) == {
        "course_level": "B2",
        "explanation_swedish_level": "B1",
    }


def test_backend_reads_prompts_from_materials():
    assert PROMPTS_DIR.name == "Materials"
    assert (PROMPTS_DIR / "Interactor_prompt.md").is_file()
    assert (PROMPTS_DIR / "Generator_prompt.md").is_file()
    assert (PROMPTS_DIR / "Shared_base_prompt.md").is_file()
    assert (PROMPTS_DIR / "Vocabulary_interactor_prompt.md").is_file()
    assert (PROMPTS_DIR / "Evaluator_prompt.md").is_file()


def test_build_generated_lesson_adds_app_fields():
    draft = {
        "lesson_id": "b1_s1_w1_d1",
        "dialogue": [
            {"speaker": "Anna" if index % 2 == 0 else "Erik", "text": f"Line {index}"}
            for index in range(20)
        ],
        "comprehension_questions": [
            {"id": "q1", "question_sv": "Var ar de?"},
            {"id": "q2", "question_sv": "Vad hander?"},
            {"id": "q3", "question_sv": "Hur slutar dialogen?"},
        ],
    }

    generated = build_generated_lesson(draft, "gpt-test")

    assert generated["lesson_id"] == "b1_s1_w1_d1"
    assert generated["model"] == "gpt-test"
    assert generated["schema_version"] == 1
    assert datetime.fromisoformat(generated["generated_at"].replace("Z", "+00:00")).tzinfo == UTC


def test_generated_dialogue_context_omits_comprehension_questions():
    lesson = sample_generated_lesson()

    context = generated_dialogue_object(lesson)

    assert context["lesson_id"] == lesson["lesson_id"]
    assert context["dialogue"] == lesson["dialogue"]
    assert "comprehension_questions" not in context
    assert "generated_at" not in context
    assert "model" not in context
    assert "schema_version" not in context


def test_active_comprehension_questions_uses_current_question_before_next_button():
    lesson = sample_generated_lesson()
    state = {
        "current_question_id": "q1",
    }

    assert active_comprehension_questions_object(lesson, state) == [
        {"id": "q1", "question_sv": "Var ar de?"}
    ]


def test_active_comprehension_questions_moves_only_after_state_changes():
    lesson = sample_generated_lesson()
    state = {
        "current_question_id": "q2",
    }

    assert active_comprehension_questions_object(lesson, state) == [
        {"id": "q2", "question_sv": "Vad hander?"}
    ]


def test_active_comprehension_questions_uses_current_question_until_discussion():
    lesson = sample_generated_lesson()
    state = {
        "current_question_id": "q3",
    }

    assert active_comprehension_questions_object(lesson, state) == [
        {"id": "q3", "question_sv": "Hur slutar dialogen?"}
    ]


def test_active_comprehension_questions_returns_empty_in_discussion():
    lesson = sample_generated_lesson()
    state = {
        "phase": "discussion",
        "current_question_id": None,
    }

    assert active_comprehension_questions_object(lesson, state) == []


def test_active_translation_sentence_uses_current_index():
    state = sample_translation_state(current_translation_index=2)

    assert active_translation_sentence_object(state) == {
        "index": 2,
        "sentence_number": 3,
        "sentence_count": 5,
        "sentence_en": "Sentence 3",
    }


def test_interactor_lesson_state_trims_translation_quiz_to_active_sentence():
    state = sample_translation_state(current_translation_index=2)

    visible_state = interactor_lesson_state_object(state)

    assert visible_state["translation_quiz"]["sentences_en"] == ["Sentence 3"]
    assert visible_state["current_translation_index"] == 0
    assert state["translation_quiz"]["sentences_en"] == [
        "Sentence 1",
        "Sentence 2",
        "Sentence 3",
        "Sentence 4",
        "Sentence 5",
    ]


def test_interactor_lesson_state_omits_operational_metadata():
    state = sample_lesson_state()
    state["audio_file_name"] = "lesson.wav"
    state["updated_at"] = "2026-08-17T12:00:00Z"

    visible_state = interactor_lesson_state_object(state)

    assert "audio_file_name" not in visible_state
    assert "updated_at" not in visible_state


def test_generated_lesson_validation_rejects_wrong_line_count():
    draft = {
        "lesson_id": "b1_s1_w1_d1",
        "dialogue": [{"speaker": "Anna", "text": "Hej"}],
        "comprehension_questions": [],
    }

    try:
        validate_generated_lesson_draft(draft, {"id": "b1_s1_w1_d1"})
    except ValueError as error:
        assert "20 lines" in str(error)
    else:
        raise AssertionError("expected validation error")


def test_sanitized_interactor_response_clears_progression_patch_fields():
    response = sample_interactor_response(
        phase="discussion",
        current_question_id="q2",
    )

    sanitized = sanitized_interactor_response(response)

    assert sanitized["state_patch"]["phase"] is None
    assert sanitized["state_patch"]["current_question_id"] is None


def test_sanitized_interactor_response_bolds_correction_lines():
    response = sample_interactor_response(
        assistant_text=(
            "Ja, precis.\n"
            "Rättelse: De lutar åt att handla i butiken.\n"
            "Kort förklaring.\n"
            "**Naturligare:** De handlar helst i butiken.\n"
            "**Rättelse: Den här raden är redan fet.**\n"
            "Här nämns Rättelse: mitt i en mening."
        )
    )

    sanitized = sanitized_interactor_response(response)

    assert sanitized["assistant_text"] == (
        "Ja, precis.\n"
        "**Rättelse: De lutar åt att handla i butiken.**\n"
        "Kort förklaring.\n"
        "**Naturligare: De handlar helst i butiken.**\n"
        "**Rättelse: Den här raden är redan fet.**\n"
        "Här nämns Rättelse: mitt i en mening."
    )


def test_interactor_validation_rejects_discussion_phase_during_comprehension():
    response = sample_interactor_response(
        phase="discussion",
        current_question_id="q1",
    )

    try:
        validate_interactor_response(response, sample_generated_lesson(), sample_lesson_state(), "svar")
    except ValueError as error:
        assert "cannot advance lesson phase" in str(error)
    else:
        raise AssertionError("expected validation error")


def test_interactor_validation_rejects_translation_phase_during_comprehension():
    response = sample_interactor_response(phase="translation")

    try:
        validate_interactor_response(response, sample_generated_lesson(), sample_lesson_state(), "svar")
    except ValueError as error:
        assert "cannot advance lesson phase" in str(error)
    else:
        raise AssertionError("expected validation error")


def test_interactor_validation_rejects_discussion_text_before_discussion_phase():
    response = sample_interactor_response(
        assistant_text="Svaret är accepterat. Du kan nu läsa dialogen igen.",
    )

    try:
        validate_interactor_response(response, sample_generated_lesson(), sample_lesson_state(), "svar")
    except ValueError as error:
        assert "discussion-stage guidance" in str(error)
    else:
        raise AssertionError("expected validation error")


def test_interactor_validation_rejects_translation_quiz_without_ui_command():
    state = sample_lesson_state(
        phase="discussion",
        current_question_id=None,
    )
    response = sample_interactor_response(translation_quiz=sample_translation_quiz())

    try:
        validate_interactor_response(response, sample_generated_lesson(), state, "start quiz")
    except ValueError as error:
        assert "start-quiz UI command" in str(error)
    else:
        raise AssertionError("expected validation error")


def test_interactor_validation_accepts_translation_quiz_for_ui_command_in_discussion():
    state = sample_lesson_state(
        phase="discussion",
        current_question_id=None,
    )
    response = sample_interactor_response(translation_quiz=sample_translation_quiz())

    validate_interactor_response(
        response,
        sample_generated_lesson(),
        state,
        "SYSTEM_UI_ACTION: start_translation_quiz",
    )


def test_prior_chat_history_omits_duplicate_latest_user_message():
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "current"},
    ]

    assert prior_chat_message_objects(messages, "current") == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
    ]


def test_append_only_history_chunks_end_at_assistant_turns_and_mark_only_complete_chunks():
    items = append_only_history_input_items(
        "prior_lesson_chat_history_json",
        [
            {"role": "assistant", "content": "Fråga 1"},
            {"role": "user", "content": "Svar 1"},
            {"role": "assistant", "content": "Feedback 1"},
            {"role": "user", "content": "Pågående"},
        ],
        cache_breakpoints=True,
    )

    assert len(items) == 3
    assert items[0]["content"][0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert items[1]["content"][0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert isinstance(items[2]["content"], str)
    assert "chunk_0001_json" in items[0]["content"][0]["text"]
    assert "chunk_0003_json" in items[2]["content"]

def test_input_section_metrics_include_hash_only_prefix_diagnostics():
    sections = _input_section_metrics(
        [
            response_input_item("stable_context_json", "{\"a\":1}"),
            response_input_item("latest_user_message", "hej"),
        ],
        instructions="system instructions",
        schema={"name": "shape"},
    )

    assert sections[0]["title"] == "stable_context_json"
    assert sections[0]["content_sha256"]
    assert sections[0]["item_sha256"]
    assert sections[0]["prompt_prefix_sha256"]
    assert "content" not in sections[0]
    assert sections[0]["prompt_prefix_sha256"] != sections[1]["prompt_prefix_sha256"]


def test_scoped_prompt_cache_key_uses_compact_stable_source_hash():
    expected_hash = hashlib.sha256("b1_s1_w1_d1".encode("utf-8")).hexdigest()[:16]

    assert scoped_prompt_cache_key("svenska_lesson_interactor_v1", " b1_s1_w1_d1 ") == (
        f"svenska_lesson_interactor_v1:{expected_hash}"
    )
    assert scoped_prompt_cache_key("svenska_lesson_interactor_v1", "") == "svenska_lesson_interactor_v1"


def test_interactor_input_places_prior_history_before_dynamic_turn_context():
    calls = []

    async def fake_send_structured_request(*_, **kwargs):
        calls.append(kwargs)
        return sample_interactor_response()

    original_send_structured_request = openai_client.send_structured_request
    openai_client.send_structured_request = fake_send_structured_request
    try:
        asyncio.run(
            openai_client.send_lesson_message(
                sample_settings(),
                payload={"id": "b1_s1_w1_d1"},
                generated_lesson=sample_generated_lesson(),
                state=sample_lesson_state(phase="comprehension", current_question_id="q1"),
                chat_history=[
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "answer"},
                    {"role": "user", "content": "current"},
                ],
                latest_user_message="current",
                model="gpt-5.6-terra",
                reasoning_effort="low",
            )
        )
    finally:
        openai_client.send_structured_request = original_send_structured_request

    assert calls[0]["prompt_cache_key"] == openai_client.scoped_prompt_cache_key(
        openai_client.INTERACTOR_PROMPT_CACHE_KEY,
        "b1_s1_w1_d1",
    )
    titles = [openai_client._input_item_text(item).split(":\n", 1)[0] for item in calls[0]["input_value"]]
    assert titles == [
        "course_context_json",
        "lesson_payload_json",
        "generated_dialogue_json",
        "prior_lesson_chat_history_chunk_0001_json",
        "active_comprehension_questions_json",
        "active_translation_sentence_json",
        "lesson_state_json",
        "latest_user_message",
    ]
    prior_history = json.loads(openai_client._input_item_text(calls[0]["input_value"][3]).split(":\n", 1)[1])
    assert prior_history == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
    ]
    for index in [1, 2, 3]:
        assert calls[0]["input_value"][index]["content"][0]["prompt_cache_breakpoint"] == {
            "mode": "explicit"
        }
    assert isinstance(calls[0]["input_value"][4]["content"], str)


def test_gpt56_request_uses_explicit_cache_blocks_and_tracks_cache_writes(monkeypatch):
    captured_body = {}
    recorded_events = []

    class FakeResponse:
        status_code = 200
        headers = {"x-request-id": "request-1"}

        @staticmethod
        def json():
            return {
                "output_text": "{}",
                "usage": {
                    "input_tokens": 2_000,
                    "input_tokens_details": {
                        "cached_tokens": 1_000,
                        "cache_write_tokens": 800,
                    },
                    "output_tokens": 100,
                    "total_tokens": 2_100,
                },
            }

    class FakeAsyncClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, *_, json, **__):
            captured_body.update(json)
            return FakeResponse()

    monkeypatch.setattr(openai_client.httpx, "AsyncClient", FakeAsyncClient)
    settings = replace(
        sample_settings(),
        openai_usage_price_overrides={
            "gpt-5.6-terra": {
                "input_per_million": 2.0,
                "cached_input_per_million": 0.2,
                "output_per_million": 12.0,
            }
        }
    )

    result = asyncio.run(
        openai_client.send_structured_request(
            settings,
            request_role="Interactor",
            user_id=1,
            request_name="cache_test",
            lesson_id="lesson-1",
            model="gpt-5.6-terra",
            reasoning_effort="low",
            instructions="stable instructions",
            input_value=[
                response_input_item("stable_json", "{}", cache_breakpoint=True),
                response_input_item("latest_user_message", "hej"),
            ],
            schema={"type": "json_schema", "name": "empty", "strict": True, "schema": {"type": "object"}},
            max_output_tokens=100,
            prompt_cache_key="cache-key",
            usage_recorder=recorded_events.append,
        )
    )

    assert result == {}
    assert "instructions" not in captured_body
    assert captured_body["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    assert "prompt_cache_retention" not in captured_body
    assert captured_body["input"][0]["role"] == "developer"
    assert captured_body["input"][0]["content"][0]["prompt_cache_breakpoint"] == {
        "mode": "explicit"
    }
    assert captured_body["input"][1]["content"][0]["prompt_cache_breakpoint"] == {
        "mode": "explicit"
    }
    assert recorded_events[0]["cached_tokens"] == 1_000
    assert recorded_events[0]["cache_write_tokens"] == 800
    assert recorded_events[0]["ordinary_input_tokens"] == 200
    assert recorded_events[0]["effective_input_cost_usd"] == 0.0026
    assert recorded_events[0]["uncached_input_cost_usd"] == 0.004
    assert recorded_events[0]["net_cache_savings_usd"] == 0.0014
    assert recorded_events[0]["estimated_cost_usd"] == 0.0038


def test_gpt55_request_keeps_legacy_retention_and_instruction_shape(monkeypatch):
    captured_body = {}

    class FakeResponse:
        status_code = 200
        headers = {}

        @staticmethod
        def json():
            return {"output_text": "{}", "usage": {}}

    class FakeAsyncClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, *_, json, **__):
            captured_body.update(json)
            return FakeResponse()

    monkeypatch.setattr(openai_client.httpx, "AsyncClient", FakeAsyncClient)
    asyncio.run(
        openai_client.send_structured_request(
            sample_settings(),
            request_role="Generator",
            request_name="legacy_cache_test",
            lesson_id="lesson-1",
            model="gpt-5.5",
            reasoning_effort="medium",
            instructions="stable instructions",
            input_value="dynamic input",
            schema={"type": "json_schema", "name": "empty", "strict": True, "schema": {"type": "object"}},
            max_output_tokens=100,
            prompt_cache_key="cache-key",
        )
    )

    assert captured_body["instructions"] == "stable instructions"
    assert captured_body["input"] == "dynamic input"
    assert captured_body["prompt_cache_retention"] == "24h"
    assert "prompt_cache_options" not in captured_body


def test_send_lesson_message_retries_invalid_interactor_response():
    calls = []

    async def fake_send_structured_request(*_, **kwargs):
        calls.append(kwargs["input_value"])
        if len(calls) == 1:
            return sample_interactor_response(
                assistant_text="Svaret är accepterat. Du kan nu läsa dialogen igen.",
                phase="discussion",
                current_question_id="q1",
            )
        return sample_interactor_response(
            assistant_text="Bra svar.",
            current_question_id="q1",
        )

    original_send_structured_request = openai_client.send_structured_request
    openai_client.send_structured_request = fake_send_structured_request
    try:
        response = asyncio.run(
            openai_client.send_lesson_message(
                sample_settings(),
                payload={"id": "b1_s1_w1_d1"},
                generated_lesson=sample_generated_lesson(),
                state=sample_lesson_state(phase="listening", current_question_id=None),
                chat_history=[],
                latest_user_message="svar",
                model="gpt-test",
                reasoning_effort="low",
            )
        )
    finally:
        openai_client.send_structured_request = original_send_structured_request

    assert response["assistant_text"] == "Bra svar."
    assert response["state_patch"]["current_question_id"] is None
    assert len(calls) == 2
    assert any("validation_error" in item["content"] for item in calls[1])


def test_interactor_response_json_is_serializable():
    response = {
        "assistant_text": "Bra.",
        "state_patch": {
            "phase": None,
            "current_question_id": None,
            "mistake_notes_add": [],
        },
        "translation_quiz": None,
    }
    assert json.loads(json.dumps(response))["assistant_text"] == "Bra."


def test_interactor_prompt_requires_structured_comprehension_feedback():
    prompt = (PROMPTS_DIR / "Interactor_prompt.md").read_text(encoding="utf-8")

    assert "**Förståelse:** Rätt." in prompt
    assert "This is the only part where a complete corrected or improved answer may appear." in prompt
    assert "Give one complete improved version by default." in prompt
    assert "Use **Rättelse** only when correcting discrete errors is sufficient" in prompt
    assert "Use **Naturligare** whenever the final version changes phrasing, word order, or collocation" in prompt
    assert "Do not label an idiomatic reformulation **Rättelse**." in prompt
    assert "If in doubt, give only **Naturligare**." in prompt
    assert "Never show near-duplicate **Rättelse** and **Naturligare** sentences." in prompt
    assert "Usually write 2–4 complete sentences." in prompt
    assert "Do not merely say that something “sounds more natural.”" in prompt
    assert "Do not summarize the learner's answer or the dialogue again." in prompt


def sample_generated_lesson():
    return {
        "lesson_id": "b1_s1_w1_d1",
        "dialogue": [
            {"speaker": "Anna" if index % 2 == 0 else "Erik", "text": f"Line {index}"}
            for index in range(20)
        ],
        "comprehension_questions": [
            {"id": "q1", "question_sv": "Var ar de?"},
            {"id": "q2", "question_sv": "Vad hander?"},
            {"id": "q3", "question_sv": "Hur slutar dialogen?"},
        ],
        "generated_at": "2026-05-24T00:00:00Z",
        "model": "gpt-test",
        "schema_version": 1,
    }


def sample_lesson_state(
    *,
    phase="comprehension",
    current_question_id="q1",
):
    return {
        "lesson_id": "b1_s1_w1_d1",
        "phase": phase,
        "current_question_id": current_question_id,
        "translation_quiz": None,
        "current_translation_index": None,
        "translation_attempts": [],
    }


def sample_interactor_response(
    *,
    assistant_text="Bra.",
    phase=None,
    current_question_id=None,
    translation_quiz=None,
):
    return {
        "assistant_text": assistant_text,
        "state_patch": {
            "phase": phase,
            "current_question_id": current_question_id,
            "mistake_notes_add": [],
        },
        "translation_quiz": translation_quiz,
    }


def sample_translation_quiz():
    return {
        "sentences_en": [
            "Sentence 1",
            "Sentence 2",
            "Sentence 3",
            "Sentence 4",
            "Sentence 5",
        ]
    }


def sample_settings():
    return Settings(
        openai_api_key="test-openai",
        gemini_api_key="test-gemini",
        app_jwt_secret="test-secret",
        apple_client_id="test-client",
        database_path=Path("test.db"),
    )


def sample_translation_state(current_translation_index=0):
    return {
        "lesson_id": "b1_s1_w1_d1",
        "phase": "translation",
        "current_question_id": "q3",
        "translation_quiz": {
            "sentences_en": [
                "Sentence 1",
                "Sentence 2",
                "Sentence 3",
                "Sentence 4",
                "Sentence 5",
            ]
        },
        "current_translation_index": current_translation_index,
        "translation_attempts": [],
    }
