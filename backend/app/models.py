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


class LessonArtifactResolveRequest(BaseModel):
    lesson_id: str = Field(min_length=1, max_length=200)
    mode: str = Field(default="shared", pattern="^(shared|private)$")


class LessonArtifactSummary(BaseModel):
    id: str
    lesson_id: str
    scope: str
    recipe_fingerprint: str
    generated_lesson: dict[str, Any]


class LessonArtifactAudioSummary(BaseModel):
    status: str
    content_hash: str | None = None


class LessonArtifactResolveResponse(BaseModel):
    resolution: str
    artifact: LessonArtifactSummary | None = None
    audio: LessonArtifactAudioSummary | None = None
    job_id: int | None = None
    status: str | None = None
    retry_after_seconds: int | None = None


class TranslationLookupRequest(BaseModel):
    selected_text: str = Field(alias="selected_text", min_length=1, max_length=500)
    source_kind: str = Field(alias="source_kind", min_length=1, max_length=40)
    source_id: str = Field(alias="source_id", min_length=1, max_length=200)
    source_surface: str | None = Field(default=None, alias="source_surface", max_length=80)
    surrounding_text: str | None = Field(default=None, alias="surrounding_text", max_length=2_000)
    visible_course_level: str | None = Field(default=None, alias="visible_course_level", max_length=10)
    created_at: str | None = Field(default=None, alias="created_at", max_length=80)

    @field_validator("selected_text", "source_kind", "source_id")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Lookup fields cannot be blank.")
        return trimmed


class LessonMessageRequest(BaseModel):
    payload: dict[str, Any]
    generated_lesson: dict[str, Any] = Field(alias="generated_lesson")
    state: dict[str, Any]
    chat_history: list[dict[str, Any]] = Field(alias="chat_history")
    latest_user_message: str = Field(alias="latest_user_message")
    model: str
    reasoning_effort: str = Field(alias="reasoning_effort")
    translation_lookup: TranslationLookupRequest | None = None


class TTSRequest(BaseModel):
    dialog: str
    model: str | None = None


class LessonSessionSummary(BaseModel):
    lesson_id: str
    status: str
    is_completed: bool
    has_audio: bool = False
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
    lesson_artifact_id: str | None = None


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
    lesson_artifact_id: str | None = None

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(value) > 500:
            raise ValueError("Too many lesson messages.")
        return value


class LessonSessionResetRequest(BaseModel):
    base_server_updated_at: str | None = None


class LessonAudioStatusResponse(BaseModel):
    lesson_id: str
    content_hash: str | None = None
    status: str
    attempt_count: int = 0
    retryable: bool = False
    updated_at: str | None = None
    error_code: str | None = None


class VocabularyPracticeMessageRequest(BaseModel):
    latest_user_message: str = Field(min_length=1, max_length=4_000)
    translation_lookup: TranslationLookupRequest | None = None

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
