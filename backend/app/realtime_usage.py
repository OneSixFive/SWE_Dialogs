from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from .config import Settings


MAX_REALTIME_TOKENS = 10_000_000
RESPONSE_ID_PATTERN = re.compile(r"resp_[A-Za-z0-9_-]{1,160}")
INPUT_MODALITIES = ("text", "audio", "image")


class RealtimeUsageError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class NormalizedRealtimeUsage:
    response_id: str
    usage: dict[str, Any]


def normalize_realtime_response_done(event: dict[str, Any]) -> NormalizedRealtimeUsage | None:
    if event.get("type") != "response.done":
        return None
    response = event.get("response")
    if not isinstance(response, dict):
        raise RealtimeUsageError("missing_response", "Realtime response.done is missing its response object.")
    response_id = response.get("id")
    if not isinstance(response_id, str) or RESPONSE_ID_PATTERN.fullmatch(response_id) is None:
        raise RealtimeUsageError("invalid_response_id", "Realtime response ID is invalid.")
    raw_usage = response.get("usage")
    if not isinstance(raw_usage, dict):
        raise RealtimeUsageError("missing_usage", "Realtime response.done is missing usage.")

    input_tokens = _token(raw_usage, "input_tokens", required=True)
    output_tokens = _token(raw_usage, "output_tokens", required=True)
    total_tokens = _token(raw_usage, "total_tokens", required=True)
    input_details = _object(raw_usage, "input_token_details", required=input_tokens > 0)
    output_details = _object(raw_usage, "output_token_details", required=output_tokens > 0)

    input_by_modality = {
        modality: _token(input_details, f"{modality}_tokens")
        for modality in INPUT_MODALITIES
    }
    cached_tokens = _token(input_details, "cached_tokens")
    cached_details = _object(input_details, "cached_tokens_details", required=cached_tokens > 0)
    cached_by_modality = {
        modality: _token(cached_details, f"{modality}_tokens")
        for modality in INPUT_MODALITIES
    }
    text_output_tokens = _token(output_details, "text_tokens")
    audio_output_tokens = _token(output_details, "audio_tokens")
    reasoning_tokens = _token(output_details, "reasoning_tokens")

    if sum(input_by_modality.values()) != input_tokens:
        raise RealtimeUsageError("input_detail_mismatch", "Realtime input token details do not match the aggregate.")
    if sum(cached_by_modality.values()) != cached_tokens:
        raise RealtimeUsageError("cached_detail_mismatch", "Realtime cached token details do not match the aggregate.")
    for modality in INPUT_MODALITIES:
        if cached_by_modality[modality] > input_by_modality[modality]:
            raise RealtimeUsageError(
                f"cached_{modality}_exceeds_input",
                f"Realtime cached {modality} tokens exceed input tokens.",
            )
    if text_output_tokens + audio_output_tokens != output_tokens:
        raise RealtimeUsageError("output_detail_mismatch", "Realtime output token details do not match the aggregate.")
    if reasoning_tokens > text_output_tokens:
        raise RealtimeUsageError(
            "reasoning_exceeds_text_output",
            "Realtime reasoning tokens exceed text output tokens.",
        )
    if input_tokens + output_tokens != total_tokens:
        raise RealtimeUsageError("total_token_mismatch", "Realtime total tokens do not match input plus output.")

    normalized_usage = {
        "total_tokens": total_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_token_details": {
            "text_tokens": input_by_modality["text"],
            "audio_tokens": input_by_modality["audio"],
            "image_tokens": input_by_modality["image"],
            "cached_tokens": cached_tokens,
            "cached_tokens_details": {
                "text_tokens": cached_by_modality["text"],
                "audio_tokens": cached_by_modality["audio"],
                "image_tokens": cached_by_modality["image"],
            },
        },
        "output_token_details": {
            "text_tokens": text_output_tokens,
            "audio_tokens": audio_output_tokens,
            "reasoning_tokens": reasoning_tokens,
        },
    }
    return NormalizedRealtimeUsage(response_id=response_id, usage=normalized_usage)


def realtime_usage_diagnostic(event: dict[str, Any]) -> str:
    """Return a bounded token-only shape summary; never include response content."""
    response = event.get("response")
    if not isinstance(response, dict):
        return '{"response_type":"non_object"}'

    status = response.get("status")
    safe_status = status if isinstance(status, str) and re.fullmatch(r"[a-z_]{1,32}", status) else None
    usage = response.get("usage")
    diagnostic: dict[str, Any] = {
        "response_status": safe_status,
        "usage_type": "object" if isinstance(usage, dict) else "missing_or_non_object",
    }
    if not isinstance(usage, dict):
        return json.dumps(diagnostic, separators=(",", ":"), sort_keys=True)

    diagnostic["usage_keys"] = _diagnostic_keys(usage)
    token_counts: dict[str, int] = {}
    _diagnostic_tokens(token_counts, "usage", usage, ("total_tokens", "input_tokens", "output_tokens"))

    for detail_key in ("input_token_details", "input_tokens_details"):
        details = usage.get(detail_key)
        if not isinstance(details, dict):
            continue
        diagnostic[f"{detail_key}_keys"] = _diagnostic_keys(details)
        _diagnostic_tokens(
            token_counts,
            detail_key,
            details,
            ("text_tokens", "audio_tokens", "image_tokens", "cached_tokens"),
        )
        for cached_key in ("cached_tokens_details", "cached_token_details"):
            cached = details.get(cached_key)
            if not isinstance(cached, dict):
                continue
            diagnostic[f"{detail_key}.{cached_key}_keys"] = _diagnostic_keys(cached)
            _diagnostic_tokens(
                token_counts,
                f"{detail_key}.{cached_key}",
                cached,
                ("text_tokens", "audio_tokens", "image_tokens"),
            )

    for detail_key in ("output_token_details", "output_tokens_details"):
        details = usage.get(detail_key)
        if not isinstance(details, dict):
            continue
        diagnostic[f"{detail_key}_keys"] = _diagnostic_keys(details)
        _diagnostic_tokens(
            token_counts,
            detail_key,
            details,
            ("text_tokens", "audio_tokens", "reasoning_tokens"),
        )

    diagnostic["token_counts"] = token_counts
    return json.dumps(diagnostic, separators=(",", ":"), sort_keys=True)


def estimated_realtime_cost_metrics(
    settings: Settings,
    model: str,
    usage: dict[str, Any],
) -> tuple[dict[str, float | None], tuple[str, ...]]:
    input_details = usage["input_token_details"]
    cached_details = input_details["cached_tokens_details"]
    output_details = usage["output_token_details"]
    model_prices = (settings.openai_usage_price_overrides or {}).get(model)
    if not isinstance(model_prices, dict):
        model_prices = {}

    components = [
        ("text_input_per_million", input_details["text_tokens"] - cached_details["text_tokens"]),
        ("text_cached_input_per_million", cached_details["text_tokens"]),
        ("audio_input_per_million", input_details["audio_tokens"] - cached_details["audio_tokens"]),
        ("audio_cached_input_per_million", cached_details["audio_tokens"]),
        ("image_input_per_million", input_details["image_tokens"] - cached_details["image_tokens"]),
        ("image_cached_input_per_million", cached_details["image_tokens"]),
        (
            "text_output_per_million",
            output_details["text_tokens"],
        ),
        ("audio_output_per_million", output_details["audio_tokens"]),
    ]
    required_rates = [
        *(key for key, tokens in components if tokens > 0),
        *(
            f"{modality}_input_per_million"
            for modality in INPUT_MODALITIES
            if input_details[f"{modality}_tokens"] > 0
        ),
    ]
    missing = tuple(
        key
        for index, key in enumerate(required_rates)
        if key not in required_rates[:index] and _price(model_prices.get(key)) is None
    )
    if missing:
        empty = {
            "estimated_cost_usd": None,
            "effective_input_cost_usd": None,
            "uncached_input_cost_usd": None,
            "net_cache_savings_usd": None,
        }
        return empty, missing

    component_costs = {
        key: tokens * (_price(model_prices.get(key)) or 0.0) / 1_000_000
        for key, tokens in components
    }
    effective_input_cost = sum(
        cost for key, cost in component_costs.items() if "input_per_million" in key
    )
    uncached_input_cost = sum(
        input_details[f"{modality}_tokens"]
        * (_price(model_prices.get(f"{modality}_input_per_million")) or 0.0)
        / 1_000_000
        for modality in INPUT_MODALITIES
    )
    output_cost = (
        component_costs["text_output_per_million"]
        + component_costs["audio_output_per_million"]
    )
    net_cache_savings = uncached_input_cost - effective_input_cost
    return (
        {
            "estimated_cost_usd": round(effective_input_cost + output_cost, 8),
            "effective_input_cost_usd": round(effective_input_cost, 8),
            "uncached_input_cost_usd": round(uncached_input_cost, 8),
            "net_cache_savings_usd": round(net_cache_savings, 8),
        },
        (),
    )


def build_speaking_usage_event(
    settings: Settings,
    *,
    user_id: int,
    lesson_id: str,
    normalized: NormalizedRealtimeUsage,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    usage = normalized.usage
    cached_tokens = usage["input_token_details"]["cached_tokens"]
    costs, missing_prices = estimated_realtime_cost_metrics(
        settings,
        settings.speaking_realtime_model,
        usage,
    )
    return (
        {
            "user_id": user_id,
            "request_role": "Speaking",
            "request_name": "speaking_turn",
            "source_id": lesson_id,
            "model": settings.speaking_realtime_model,
            "prompt_version": "speaking_realtime_v1",
            "input_tokens": usage["input_tokens"],
            "cached_tokens": cached_tokens,
            "cache_write_tokens": 0,
            "ordinary_input_tokens": usage["input_tokens"] - cached_tokens,
            "output_tokens": usage["output_tokens"],
            "reasoning_tokens": usage["output_token_details"]["reasoning_tokens"],
            "total_tokens": usage["total_tokens"],
            **costs,
            "elapsed_ms": 0,
            "provider_response_id": normalized.response_id,
            "raw_usage": usage,
        },
        missing_prices,
    )


def _object(source: dict[str, Any], key: str, *, required: bool = False) -> dict[str, Any]:
    value = source.get(key)
    if value is None and not required:
        return {}
    if not isinstance(value, dict):
        raise RealtimeUsageError(f"invalid_{key}", f"Realtime usage field {key} must be an object.")
    return value


def _token(source: dict[str, Any], key: str, *, required: bool = False) -> int:
    value = source.get(key)
    if value is None and not required:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise RealtimeUsageError(f"invalid_{key}", f"Realtime usage field {key} must be an integer.")
    if value < 0 or value > MAX_REALTIME_TOKENS:
        raise RealtimeUsageError(f"invalid_{key}", f"Realtime usage field {key} is out of range.")
    return value


def _diagnostic_keys(source: dict[str, Any]) -> list[str]:
    return sorted(
        key
        for key in source
        if isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", key)
    )[:24]


def _diagnostic_tokens(
    destination: dict[str, int],
    prefix: str,
    source: dict[str, Any],
    keys: tuple[str, ...],
) -> None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_REALTIME_TOKENS:
            destination[f"{prefix}.{key}"] = value


def _price(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    price = float(value)
    return price if math.isfinite(price) and price >= 0 else None
