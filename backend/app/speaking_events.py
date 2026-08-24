from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


PERSISTED_SPEAKING_EVENT_TYPES = frozenset(
    {
        "response.done",
        "conversation.item.input_audio_transcription.completed",
        "conversation.item.input_audio_transcription.failed",
        "input_audio_buffer.speech_started",
        "input_audio_buffer.speech_stopped",
    }
)


@dataclass(frozen=True)
class DurableSpeakingEvent:
    event_type: str
    event_key: str
    provider_event_id: str | None
    provider_response_id: str | None
    payload: dict[str, Any]


def durable_speaking_event(event: dict[str, Any]) -> DurableSpeakingEvent | None:
    event_type = event.get("type")
    if not isinstance(event_type, str) or event_type not in PERSISTED_SPEAKING_EVENT_TYPES:
        return None

    provider_event_id = _bounded_string(event.get("event_id"))
    provider_response_id = None
    response = event.get("response")
    if isinstance(response, dict):
        provider_response_id = _bounded_string(response.get("id"))

    item_id = _bounded_string(event.get("item_id"))
    content_index = event.get("content_index")
    if provider_response_id is not None:
        event_key = f"response:{provider_response_id}"
    elif (
        event_type.startswith("conversation.item.input_audio_transcription.")
        and item_id is not None
    ):
        index = (
            content_index
            if isinstance(content_index, int) and not isinstance(content_index, bool)
            else 0
        )
        event_key = f"input-transcription:{event_type}:{item_id}:{index}"
    elif provider_event_id is not None:
        event_key = f"event:{provider_event_id}"
    else:
        canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        event_key = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"

    return DurableSpeakingEvent(
        event_type=event_type,
        event_key=event_key,
        provider_event_id=provider_event_id,
        provider_response_id=provider_response_id,
        payload=event,
    )


def _bounded_string(value: object, *, max_length: int = 255) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and len(value) <= max_length else None
