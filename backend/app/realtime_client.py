from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .config import Settings


REALTIME_CALLS_URL = "https://api.openai.com/v1/realtime/calls"
MAX_SDP_ANSWER_BYTES = 128 * 1024
CALL_ID_PATTERN = re.compile(r"call_[A-Za-z0-9_-]{1,128}")


@dataclass(frozen=True)
class RealtimeCallAnswer:
    sdp: str
    call_id: str | None


class RealtimeBootstrapError(Exception):
    def __init__(
        self,
        message: str,
        *,
        temporary: bool,
        provider_status: int | None = None,
        provider_code: str | None = None,
        provider_type: str | None = None,
        provider_param: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.temporary = temporary
        self.provider_status = provider_status
        self.provider_code = provider_code
        self.provider_type = provider_type
        self.provider_param = provider_param
        self.request_id = request_id

    def public_detail(self) -> str:
        details = []
        if self.provider_status is not None:
            details.append(f"status {self.provider_status}")
        if self.provider_code:
            details.append(f"code {self.provider_code}")
        if self.provider_param:
            details.append(f"field {self.provider_param}")
        if not details:
            return str(self)
        return f"{self} Provider: {', '.join(details)}."


class RealtimeHangupError(Exception):
    pass


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
        metadata = _provider_error_metadata(response)
        raise RealtimeBootstrapError(
            "Realtime service rejected session initialization.",
            temporary=temporary,
            provider_status=response.status_code,
            **metadata,
        )
    if len(response.content) > MAX_SDP_ANSWER_BYTES:
        raise RealtimeBootstrapError("Realtime service returned an invalid SDP answer.", temporary=False)
    sdp = response.text.strip()
    if not sdp.startswith("v=0") or "m=audio" not in sdp:
        raise RealtimeBootstrapError("Realtime service returned an invalid SDP answer.", temporary=False)
    return RealtimeCallAnswer(sdp=sdp, call_id=_call_id(response.headers.get("Location")))


async def hangup_realtime_call(settings: Settings, *, call_id: str) -> None:
    if CALL_ID_PATTERN.fullmatch(call_id) is None:
        raise ValueError("Invalid Realtime call ID.")
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    timeout = httpx.Timeout(max(min(settings.speaking_realtime_timeout_seconds, 10.0), 1.0))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{REALTIME_CALLS_URL}/{call_id}/hangup", headers=headers)
    except httpx.HTTPError as error:
        raise RealtimeHangupError("Realtime call hangup failed.") from error

    if 200 <= response.status_code < 300 or response.status_code in {404, 409}:
        return
    raise RealtimeHangupError("Realtime call hangup was rejected.")


def _call_id(location: str | None) -> str | None:
    if not location:
        return None
    value = urlparse(location).path.rstrip("/").rsplit("/", 1)[-1]
    return value if CALL_ID_PATTERN.fullmatch(value) is not None else None


def _provider_error_metadata(response: httpx.Response) -> dict[str, str | None]:
    """Extract only bounded identifiers; never retain the provider message/body."""
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    if not isinstance(error, dict):
        error = {}
    return {
        "provider_code": _safe_identifier(error.get("code")),
        "provider_type": _safe_identifier(error.get("type")),
        "provider_param": _safe_identifier(error.get("param")),
        "request_id": _safe_identifier(response.headers.get("x-request-id")),
    }


def _safe_identifier(value: object, *, max_length: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > max_length:
        return None
    return value if re.fullmatch(r"[A-Za-z0-9_.\[\]-]+", value) is not None else None
