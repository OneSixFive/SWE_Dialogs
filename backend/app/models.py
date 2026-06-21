from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class AppleAuthRequest(BaseModel):
    id_token: str = Field(alias="id_token")
    nonce: str | None = None


class UserSummary(BaseModel):
    id: int
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


class LessonSessionSummary(BaseModel):
    lesson_id: str
    status: str
    is_completed: bool
    completed_at: str | None = None
    client_updated_at: str
    server_updated_at: str


class LessonSessionResponse(LessonSessionSummary):
    state: dict[str, Any]
    generated_lesson: dict[str, Any] | None = None
    messages: list[dict[str, Any]]
    chat_summary: dict[str, Any] | None = None
    state_schema_version: int
    content_schema_version: int


class LessonSessionsResponse(BaseModel):
    sessions: list[dict[str, Any]]


class LessonProgressSyncRequest(BaseModel):
    completed_lesson_ids: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("completed_lesson_ids")
    @classmethod
    def validate_completed_lesson_ids(cls, value: list[str]) -> list[str]:
        normalized = [lesson_id.strip() for lesson_id in value]
        if any(not lesson_id for lesson_id in normalized):
            raise ValueError("Completed lesson IDs cannot be blank.")
        return list(dict.fromkeys(normalized))


class LessonProgressSyncResponse(BaseModel):
    completed_count: int
    course_level: str
    stage_number: int
    current_lesson_id: str


class LessonSessionUpsertRequest(BaseModel):
    state: dict[str, Any]
    generated_lesson: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    chat_summary: dict[str, Any] | None = None
    client_updated_at: str
    base_server_updated_at: str | None = None
    reset_generation: bool = False

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(value) > 500:
            raise ValueError("Too many lesson messages.")
        return value


class LessonSessionResetRequest(BaseModel):
    base_server_updated_at: str | None = None


class VocabularyPracticeMessageRequest(BaseModel):
    latest_user_message: str = Field(min_length=1, max_length=4_000)

    @field_validator("latest_user_message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Message cannot be blank.")
        return trimmed


class VocabularyPracticeSummary(BaseModel):
    id: str
    course_level: str
    stage_number: int
    status: str
    current_question_index: int
    answered_count: int
    created_at: str
    updated_at: str
    completed_at: str | None = None


class VocabularyPracticesResponse(BaseModel):
    practices: list[VocabularyPracticeSummary]


class VocabularyPracticeResponse(VocabularyPracticeSummary):
    progress_cutoff_absolute_day: int
    quiz: dict[str, Any] | None = None
    state: dict[str, Any]
    messages: list[dict[str, Any]]
