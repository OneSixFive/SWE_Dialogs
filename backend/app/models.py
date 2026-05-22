from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AppleAuthRequest(BaseModel):
    id_token: str = Field(alias="id_token")
    nonce: str | None = None


class UserSummary(BaseModel):
    id: int
    apple_sub: str = Field(alias="apple_sub")
    email: str | None = None


class AppleAuthResponse(BaseModel):
    session_token: str = Field(alias="session_token")
    user: UserSummary


class LessonGenerateRequest(BaseModel):
    payload: dict[str, Any]
    model: str
    reasoning_effort: str = Field(alias="reasoning_effort")


class LessonMessageRequest(BaseModel):
    payload: dict[str, Any]
    generated_lesson: dict[str, Any] = Field(alias="generated_lesson")
    state: dict[str, Any]
    chat_history: list[dict[str, Any]] = Field(alias="chat_history")
    latest_user_message: str = Field(alias="latest_user_message")
    model: str
    reasoning_effort: str = Field(alias="reasoning_effort")


class TTSRequest(BaseModel):
    dialog: str
    model: str | None = None
