from __future__ import annotations

import hashlib
import re
import secrets
from typing import Literal
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .auth import (
    get_database,
    get_settings,
    issue_session_token,
    verify_apple_identity_token,
    verify_google_identity_token,
)
from .config import Settings
from .db import Database
from .models import AppleAuthResponse, UserSummary


router = APIRouter(prefix="/auth")
TOKEN_PATTERN = r"^[A-Za-z0-9_-]{43}$"
APPLE_CALLBACK_PATH = "/auth/android/apple/callback"


class StartRequest(BaseModel):
    provider: Literal["apple", "google"]
    verifier_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class StartResponse(BaseModel):
    state: str
    authorization_url: str | None = None


class ExchangeRequest(BaseModel):
    state: str = Field(pattern=TOKEN_PATTERN)
    verifier: str = Field(pattern=TOKEN_PATTERN)


class GoogleExchangeRequest(ExchangeRequest):
    id_token: str = Field(min_length=1, max_length=8192)


@router.post("/android/start", response_model=StartResponse)
def start_android_auth(
    request: StartRequest,
    settings: Settings = Depends(get_settings),
    database: Database = Depends(get_database),
) -> StartResponse:
    state = secrets.token_urlsafe(32)
    authorization_url = None
    if request.provider == "apple":
        redirect = urlsplit(settings.apple_android_redirect_uri or "")
        if (
            not settings.apple_services_id
            or redirect.scheme != "https"
            or not redirect.hostname
            or redirect.path != APPLE_CALLBACK_PATH
            or redirect.query
            or redirect.fragment
        ):
            raise HTTPException(status_code=503, detail="Apple sign-in is unavailable.")
        query = urlencode({
            "client_id": settings.apple_services_id,
            "redirect_uri": settings.apple_android_redirect_uri,
            "response_type": "code id_token",
            "response_mode": "form_post",
            "scope": "email",
            "state": state,
            "nonce": state,
        })
        authorization_url = f"https://appleid.apple.com/auth/authorize?{query}"
    elif not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is unavailable.")
    database.create_android_auth_request(state, request.provider, request.verifier_hash)
    return StartResponse(state=state, authorization_url=authorization_url)


@router.post("/android/apple/callback", response_class=HTMLResponse)
async def android_apple_callback(
    request: Request,
    settings: Settings = Depends(get_settings),
    database: Database = Depends(get_database),
) -> HTMLResponse:
    if not settings.apple_services_id:
        raise HTTPException(status_code=503, detail="Apple sign-in is unavailable.")
    media_type = request.headers.get("content-type", "").partition(";")[0]
    if media_type != "application/x-www-form-urlencoded":
        raise HTTPException(status_code=415, detail="Expected an Apple form response.")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 16384:
            raise HTTPException(status_code=413, detail="Apple response is too large.")
        body.extend(chunk)
    fields: dict[str, list[str]] = {}
    try:
        fields = parse_qs(body.decode("utf-8"), max_num_fields=12)
        (state,) = fields["state"]
        if not re.fullmatch(TOKEN_PATTERN, state):
            raise ValueError
        (id_token,) = fields["id_token"]
    except (KeyError, ValueError) as error:
        if fields.get("error") == ["user_cancelled_authorize"]:
            return HTMLResponse("Inloggningen avbröts. Stäng fliken för att återgå till Jaha.")
        raise HTTPException(status_code=400, detail="Invalid Apple sign-in response.") from error

    claims = await run_in_threadpool(
        verify_apple_identity_token, id_token, state, settings, audience=settings.apple_services_id
    )
    if claims.get("nonce") != state:
        raise HTTPException(status_code=401, detail="Invalid Apple nonce.")
    completed = await run_in_threadpool(
        database.complete_android_apple_request, state, claims["sub"], claims.get("email")
    )
    if not completed:
        raise HTTPException(status_code=400, detail="Apple sign-in expired or was already completed.")
    return HTMLResponse(
        '<!doctype html><html lang="sv"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Jaha</title><p>Fortsätt i Jaha för att slutföra inloggningen.</p>'
        f'<a href="intent://apple?state={state}#Intent;scheme=jaha-auth;package=se.jaha.android;end">'
        'Öppna Jaha</a></html>',
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post("/android/apple/exchange", response_model=AppleAuthResponse)
def exchange_android_apple(
    request: ExchangeRequest,
    settings: Settings = Depends(get_settings),
    database: Database = Depends(get_database),
) -> AppleAuthResponse:
    if not settings.apple_services_id:
        raise HTTPException(status_code=503, detail="Apple sign-in is unavailable.")
    auth_request = database.consume_android_auth_request(request.state, "apple", _verifier_hash(request))
    if auth_request is None:
        raise HTTPException(status_code=401, detail="Invalid or expired Apple sign-in.")
    return _sign_in(database, settings, auth_request["apple_subject"], auth_request["email"])


@router.post("/google", response_model=AppleAuthResponse)
def auth_google(
    request: GoogleExchangeRequest,
    settings: Settings = Depends(get_settings),
    database: Database = Depends(get_database),
) -> AppleAuthResponse:
    claims = verify_google_identity_token(request.id_token, request.state, settings)
    if database.consume_android_auth_request(request.state, "google", _verifier_hash(request)) is None:
        raise HTTPException(status_code=401, detail="Invalid or expired Google sign-in.")
    email = claims.get("email") if claims.get("email_verified") is True else None
    # The original users.apple_sub column also serves as the session subject.
    return _sign_in(database, settings, f"google:{claims['sub']}", email)


def _verifier_hash(request: ExchangeRequest) -> str:
    return hashlib.sha256(request.verifier.encode("ascii")).hexdigest()


def _sign_in(database: Database, settings: Settings, subject: str, email: str | None) -> AppleAuthResponse:
    user = database.find_or_create_user(subject, email)
    return AppleAuthResponse(
        session_token=issue_session_token(subject, settings),
        user=UserSummary(id=user.id, email=user.email),
    )
