from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .config import Settings


REALTIME_CALLS_URL = "https://api.openai.com/v1/realtime/calls"
MAX_SDP_ANSWER_BYTES = 128 * 1024


@dataclass(frozen=True)
class RealtimeCallAnswer:
    sdp: str
    call_id: str | None


class RealtimeBootstrapError(Exception):
    def __init__(self, message: str, *, temporary: bool) -> None:
        super().__init__(message)
        self.temporary = temporary


async def create_realtime_call(
    settings: Settings,
    *,
    sdp_offer: str,
    session_config: dict,
    safety_identifier: str,
) -> RealtimeCallAnswer:
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "OpenAI-Safety-Identifier": safety_identifier,
    }
    files = {
        "sdp": (None, sdp_offer, "application/sdp"),
        "session": (
            None,
            json.dumps(session_config, ensure_ascii=False, separators=(",", ":")),
            "application/json",
        ),
    }
    timeout = httpx.Timeout(settings.speaking_realtime_timeout_seconds)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(REALTIME_CALLS_URL, headers=headers, files=files)
    except (httpx.TimeoutException, httpx.NetworkError) as error:
        raise RealtimeBootstrapError("Realtime service is temporarily unavailable.", temporary=True) from error
    except httpx.HTTPError as error:
        raise RealtimeBootstrapError("Realtime session initialization failed.", temporary=True) from error

    if not 200 <= response.status_code < 300:
        temporary = response.status_code == 429 or response.status_code >= 500
        raise RealtimeBootstrapError("Realtime service rejected session initialization.", temporary=temporary)
    if len(response.content) > MAX_SDP_ANSWER_BYTES:
        raise RealtimeBootstrapError("Realtime service returned an invalid SDP answer.", temporary=False)
    sdp = response.text.strip()
    if not sdp.startswith("v=0") or "m=audio" not in sdp:
        raise RealtimeBootstrapError("Realtime service returned an invalid SDP answer.", temporary=False)
    return RealtimeCallAnswer(sdp=sdp, call_id=_call_id(response.headers.get("Location")))


def _call_id(location: str | None) -> str | None:
    if not location:
        return None
    value = urlparse(location).path.rstrip("/").rsplit("/", 1)[-1]
    return value if value.startswith("call_") else None
