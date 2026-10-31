from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import anthropic
from fastapi import HTTPException, status

from .config import Settings
from .openai_client import (
    UsageRecorder,
    _estimated_cost_metrics,
    _input_item_text,
    append_only_history_input_items,
    json_string,
    logger,
    response_input_item,
    short_sha256,
    speaker_schema,
)


ANTHROPIC_FALLBACK_BETA = "server-side-fallback-2026-07-01"
ANTHROPIC_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


@lru_cache(maxsize=4)
def _client(api_key: str, timeout_seconds: float) -> anthropic.AsyncAnthropic:
    # One long-lived client per key keeps the HTTPS connection warm between Speaking turns.
    return anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_seconds, max_retries=1)


def _effort(reasoning_effort: str) -> str:
    effort = reasoning_effort.strip().lower()
    return effort if effort in ANTHROPIC_EFFORTS else "low"


def _text_block(item: dict[str, Any], *, cache: bool = False) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "text", "text": _input_item_text(item)}
    if cache:
        block["cache_control"] = {"type": "ephemeral"}
    return block


async def send_speaker_turn_anthropic(
    settings: Settings,
    *,
    user_id: int,
    lesson_id: str,
    instructions: str,
    prior_messages: list[dict[str, str]],
    speaker_state: dict[str, Any],
    latest_learner_transcript: str | None,
    usage_recorder: UsageRecorder | None = None,
) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Anthropic is not configured.")
    model = settings.speaker_model

    # Same cache-first order as the OpenAI Speaker: instructions (system), append-only history
    # chunks, then per-turn state and transcript. History chunks end on tutor turns, so the last one
    # is complete and byte-stable; its breakpoint is what the next turn reads back.
    history_items = append_only_history_input_items(
        "prior_speaking_history_json",
        prior_messages,
        cache_breakpoints=False,
    )
    history_complete = bool(prior_messages) and prior_messages[-1].get("role") == "assistant"
    blocks = [
        _text_block(item, cache=history_complete and index == len(history_items) - 1)
        for index, item in enumerate(history_items)
    ]
    blocks.append(_text_block(response_input_item("speaker_state_json", json_string(speaker_state))))
    if latest_learner_transcript is not None:
        blocks.append(_text_block(response_input_item("latest_learner_transcript", latest_learner_transcript)))

    schema = speaker_schema()
    started = time.perf_counter()
    try:
        response = await _client(settings.anthropic_api_key, settings.speaker_provider_timeout_seconds).beta.messages.create(
            model=model,
            max_tokens=4_000,
            system=[{"type": "text", "text": instructions, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": blocks}],
            output_config={
                "effort": _effort(settings.speaker_reasoning_effort),
                "format": {"type": "json_schema", "schema": schema["schema"]},
            },
            betas=[ANTHROPIC_FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.APIStatusError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Anthropic error: {error.message}",
        ) from error
    except anthropic.APIConnectionError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Anthropic connection failed.") from error
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    usage_event = _log_anthropic_usage(
        settings,
        user_id=user_id,
        lesson_id=lesson_id,
        model=model,
        instructions=instructions,
        blocks=blocks,
        response=response,
        elapsed_ms=elapsed_ms,
    )
    if usage_recorder is not None:
        usage_recorder(usage_event)

    if response.stop_reason == "refusal":
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Anthropic refused the request.")
    output_text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not output_text:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Anthropic returned no structured output.")
    try:
        decoded = json.loads(output_text)
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Anthropic returned invalid structured JSON.",
        ) from error
    if not isinstance(decoded, dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Anthropic returned unexpected JSON.")
    return decoded


def _log_anthropic_usage(
    settings: Settings,
    *,
    user_id: int,
    lesson_id: str,
    model: str,
    instructions: str,
    blocks: list[dict[str, Any]],
    response: Any,
    elapsed_ms: int,
) -> dict[str, Any]:
    raw_usage = response.usage.to_dict()
    uncached = response.usage.input_tokens or 0
    cache_read = response.usage.cache_read_input_tokens or 0
    cache_write = response.usage.cache_creation_input_tokens or 0
    output_tokens = response.usage.output_tokens or 0
    input_tokens = uncached + cache_read + cache_write
    # OpenAI-shaped usage so the shared price table and dashboard math apply unchanged.
    cost_metrics = _estimated_cost_metrics(
        settings,
        model,
        {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "input_tokens_details": {"cached_tokens": cache_read, "cache_write_tokens": cache_write},
        },
    )
    request_id = getattr(response, "_request_id", None)
    logger.info(
        "anthropic_response_usage %s",
        json.dumps(
            {
                "request": "speaker_turn",
                "model": model,
                "served_model": response.model,
                "lesson_id": lesson_id,
                "stop_reason": response.stop_reason,
                "elapsed_ms": elapsed_ms,
                "anthropic_request_id": request_id,
                "instructions_sha256": short_sha256(instructions),
                "input_blocks": len(blocks),
                "input_tokens": input_tokens,
                "cached_tokens": cache_read,
                "cache_write_tokens": cache_write,
                "ordinary_input_tokens": uncached,
                "output_tokens": output_tokens,
                "cache_read_ratio": round(cache_read / input_tokens, 4) if input_tokens else None,
                **cost_metrics,
            },
            sort_keys=True,
        ),
    )
    return {
        "user_id": user_id,
        "request_role": "Speaking",
        "request_name": "speaker_turn",
        "source_id": lesson_id,
        "model": model,
        "prompt_version": "speaker_v1",
        "prompt_cache_key": None,
        "input_tokens": input_tokens,
        "cached_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "ordinary_input_tokens": uncached,
        "output_tokens": output_tokens,
        "reasoning_tokens": None,
        "total_tokens": input_tokens + output_tokens,
        **cost_metrics,
        "actual_cost_usd": None,
        "elapsed_ms": elapsed_ms,
        "openai_request_id": request_id,
        "created_at": datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "raw_usage": raw_usage,
    }
