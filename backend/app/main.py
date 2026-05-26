from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Response, status

from .auth import CurrentUser, get_database, get_settings, issue_session_token, require_user, verify_apple_identity_token
from .config import Settings
from .db import Database, LessonSession, LessonSessionConflict
from .gemini_client import generate_wav
from .models import (
    AppleAuthRequest,
    AppleAuthResponse,
    LessonGenerateRequest,
    LessonMessageRequest,
    LessonSessionResetRequest,
    LessonSessionResponse,
    LessonSessionsResponse,
    LessonSessionSummary,
    LessonSessionUpsertRequest,
    TTSRequest,
    UserSummary,
)
from .openai_client import generate_lesson, send_lesson_message


app = FastAPI(title="Svenska Backend", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "svenska-backend"}


@app.post("/auth/apple", response_model=AppleAuthResponse)
async def auth_apple(
    request: AppleAuthRequest,
    settings: Settings = Depends(get_settings),
    database: Database = Depends(get_database),
) -> AppleAuthResponse:
    claims = verify_apple_identity_token(request.id_token, request.nonce, settings)
    user = database.find_or_create_user(
        apple_sub=str(claims["sub"]),
        email=claims.get("email"),
    )
    session_token = issue_session_token(user.apple_sub, settings)
    return AppleAuthResponse(
        session_token=session_token,
        user=UserSummary(id=user.id, email=user.email),
    )


@app.get("/me", response_model=UserSummary)
async def me(current_user: CurrentUser = Depends(require_user), database: Database = Depends(get_database)) -> UserSummary:
    user = database.find_user_by_apple_sub(current_user.apple_sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown session user.")
    return UserSummary(id=user.id, email=user.email)


@app.get("/me/lesson-sessions", response_model=LessonSessionsResponse)
async def list_lesson_sessions(
    summary_only: bool = True,
    updated_after: str | None = None,
    limit: int = 500,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
) -> LessonSessionsResponse:
    bounded_limit = min(max(limit, 1), 1000)
    rows = database.list_lesson_sessions(
        user_id=current_user.user_id,
        updated_after=updated_after,
        limit=bounded_limit,
    )
    sessions = [
        (_lesson_session_summary(row) if summary_only else _lesson_session_response(row)).model_dump(by_alias=True)
        for row in rows
    ]
    return LessonSessionsResponse(sessions=sessions)


@app.get("/me/lesson-sessions/{lesson_id}", response_model=LessonSessionResponse)
async def get_lesson_session(
    lesson_id: str,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
) -> LessonSessionResponse:
    row = database.get_lesson_session(user_id=current_user.user_id, lesson_id=lesson_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson session not found.")
    return _lesson_session_response(row)


@app.put("/me/lesson-sessions/{lesson_id}", response_model=LessonSessionResponse)
async def put_lesson_session(
    lesson_id: str,
    request: LessonSessionUpsertRequest,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
) -> LessonSessionResponse:
    _validate_lesson_session_payload(lesson_id, request)
    try:
        row = database.upsert_lesson_session(
            user_id=current_user.user_id,
            lesson_id=lesson_id,
            state=request.state,
            generated_lesson=request.generated_lesson,
            messages=request.messages,
            chat_summary=request.chat_summary,
            client_updated_at=request.client_updated_at,
            base_server_updated_at=request.base_server_updated_at,
            reset_generation=request.reset_generation,
        )
    except LessonSessionConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Lesson session has newer server state.",
                "current": _lesson_session_response(error.current).model_dump(by_alias=True),
            },
        ) from error
    return _lesson_session_response(row)


@app.post("/me/lesson-sessions/{lesson_id}/reset", response_model=LessonSessionResponse)
async def reset_lesson_session(
    lesson_id: str,
    request: LessonSessionResetRequest,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
) -> LessonSessionResponse:
    try:
        row = database.reset_lesson_session(
            user_id=current_user.user_id,
            lesson_id=lesson_id,
            base_server_updated_at=request.base_server_updated_at,
        )
    except LessonSessionConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Lesson session has newer server state.",
                "current": _lesson_session_response(error.current).model_dump(by_alias=True),
            },
        ) from error
    return _lesson_session_response(row)


@app.post("/lessons/generate")
async def lessons_generate(
    request: LessonGenerateRequest,
    _: CurrentUser = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        return await generate_lesson(
            settings,
            payload=request.payload,
            model=request.model,
            reasoning_effort=request.reasoning_effort,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error


@app.post("/lessons/message")
async def lessons_message(
    request: LessonMessageRequest,
    _: CurrentUser = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        return await send_lesson_message(
            settings,
            payload=request.payload,
            generated_lesson=request.generated_lesson,
            state=request.state,
            chat_history=request.chat_history,
            latest_user_message=request.latest_user_message,
            model=request.model,
            reasoning_effort=request.reasoning_effort,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error


@app.post("/tts/dialogue")
async def tts_dialogue(
    request: TTSRequest,
    _: CurrentUser = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> Response:
    wav_data = await generate_wav(settings, dialog=request.dialog, model=request.model)
    return Response(content=wav_data, media_type="audio/wav")


def _lesson_session_summary(row: LessonSession) -> LessonSessionSummary:
    return LessonSessionSummary(
        lesson_id=row.lesson_id,
        status=row.status,
        is_completed=row.is_completed,
        completed_at=row.completed_at,
        client_updated_at=row.client_updated_at,
        server_updated_at=row.server_updated_at,
    )


def _lesson_session_response(row: LessonSession) -> LessonSessionResponse:
    return LessonSessionResponse(
        **_lesson_session_summary(row).model_dump(by_alias=True),
        state=row.state,
        generated_lesson=row.generated_lesson,
        messages=row.messages,
        chat_summary=row.chat_summary,
        state_schema_version=row.state_schema_version,
        content_schema_version=row.content_schema_version,
    )


def _validate_lesson_session_payload(lesson_id: str, request: LessonSessionUpsertRequest) -> None:
    state_lesson_id = request.state.get("lesson_id")
    if state_lesson_id != lesson_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="State lesson_id must match path.")

    phase = request.state.get("phase")
    valid_phases = {
        "notStarted",
        "not_started",
        "generated",
        "listening",
        "comprehension",
        "discussion",
        "translation",
        "completed",
    }
    if phase not in valid_phases:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid lesson phase.")

    phases_requiring_generated_lesson = {"generated", "listening", "comprehension", "discussion", "translation"}
    if phase in phases_requiring_generated_lesson and request.generated_lesson is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="generated_lesson is required once a lesson has generated content.",
        )

    if request.generated_lesson is not None and request.generated_lesson.get("lesson_id") != lesson_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="generated_lesson lesson_id must match path.",
        )

    for message in request.messages:
        if message.get("lesson_id") != lesson_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Message lesson_id must match path.",
            )
        if message.get("role") not in {"user", "assistant"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid message role.")
