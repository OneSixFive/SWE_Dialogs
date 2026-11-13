from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient

from .config import Settings, load_settings
from .db import Database


APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
SESSION_ISSUER = "svenska-backend"
SESSION_TTL = timedelta(days=14)

_apple_jwks_client = PyJWKClient(APPLE_JWKS_URL)
_google_jwks_client = PyJWKClient("https://www.googleapis.com/oauth2/v3/certs", timeout=5)
_settings: Settings | None = None
_database: Database | None = None


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    apple_sub: str


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def get_database() -> Database:
    global _database
    if _database is None:
        _database = Database(get_settings().database_path)
    return _database


def verify_apple_identity_token(
    id_token: str, nonce: str | None, settings: Settings, *, audience: str | None = None
) -> dict[str, Any]:
    try:
        signing_key = _apple_jwks_client.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience or settings.apple_client_id,
            issuer=APPLE_ISSUER,
            options={"require": ["iss", "sub", "aud", "exp"]},
        )
    except jwt.PyJWTError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Apple identity token.",
        ) from error

    if nonce:
        expected_nonce = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        token_nonce = claims.get("nonce")
        if token_nonce not in {expected_nonce, nonce}:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Apple nonce.",
            )

    if not claims.get("sub") or ":" in claims["sub"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Apple identity token.",
        )
    return claims


def verify_google_identity_token(id_token: str, nonce: str, settings: Settings) -> dict[str, Any]:
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is unavailable.")
    try:
        signing_key = _google_jwks_client.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer=("https://accounts.google.com", "accounts.google.com"),
            options={"require": ["iss", "sub", "aud", "exp", "iat"], "strict_aud": True},
        )
        if not claims["sub"] or claims.get("nonce") != nonce:
            raise jwt.InvalidTokenError()
    except jwt.PyJWKClientConnectionError as error:
        raise HTTPException(status_code=503, detail="Google sign-in is temporarily unavailable.") from error
    except jwt.PyJWTError as error:
        raise HTTPException(status_code=401, detail="Invalid Google identity token.") from error
    return claims


def issue_session_token(apple_sub: str, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": SESSION_ISSUER,
        "sub": apple_sub,
        "iat": int(now.timestamp()),
        "exp": int((now + SESSION_TTL).timestamp()),
    }
    return jwt.encode(payload, settings.app_jwt_secret, algorithm="HS256")


def decode_session_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.app_jwt_secret,
            algorithms=["HS256"],
            issuer=SESSION_ISSUER,
            options={"require": ["iss", "sub", "exp"]},
        )
    except jwt.PyJWTError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session.",
        ) from error


def require_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    database: Database = Depends(get_database),
) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing session token.",
        )

    token = authorization.split(" ", 1)[1].strip()
    claims = decode_session_token(token, settings)
    apple_sub = str(claims["sub"])
    user = database.find_user_by_apple_sub(apple_sub)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown session user.",
        )
    return CurrentUser(user_id=user.id, apple_sub=user.apple_sub)
