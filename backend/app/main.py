from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, HTTPException, Response, status

from .auth import CurrentUser, get_database, get_settings, issue_session_token, require_user, verify_apple_identity_token
from .config import Settings
from .db import Database, LessonSession, LessonSessionConflict, VocabularyPracticeSession
from .evaluation_worker import evaluation_worker_loop
from .gemini_client import generate_wav
from .learning_catalog import get_learning_catalog
from .learning_service import (
    build_lesson_evaluation_snapshot,
    select_practice_targets,
    validate_vocabulary_interaction,
    validate_vocabulary_quiz,
    vocabulary_interactor_context,
)
from .models import (
    AppleAuthRequest,
    AppleAuthResponse,
    LessonGenerateRequest,
    LessonMessageRequest,
    LessonProgressSyncRequest,
    LessonProgressSyncResponse,
    LessonSessionResetRequest,
    LessonSessionResponse,
    LessonSessionsResponse,
    LessonSessionSummary,
    LessonSessionUpsertRequest,
    TTSRequest,
    UserSummary,
    VocabularyPracticeMessageRequest,
    VocabularyPracticeResponse,
    VocabularyPracticesResponse,
    VocabularyPracticeSummary,
)
from .openai_client import (
    generate_lesson,
    generate_vocabulary_quiz,
    send_lesson_message,
    send_vocabulary_message,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker: asyncio.Task[None] | None = None
    try:
        settings = get_settings()
        database = get_database()
        if settings.evaluation_worker_enabled:
            worker = asyncio.create_task(evaluation_worker_loop(database, settings))
    except RuntimeError:
        # Local contract tests can construct the app without production secrets.
        worker = None
    try:
        yield
    finally:
        if worker is not None:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker


app = FastAPI(title="Svenska Backend", version="0.2.0", lifespan=lifespan)


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


@app.post("/me/lesson-progress/sync", response_model=LessonProgressSyncResponse)
async def sync_lesson_progress(
    request: LessonProgressSyncRequest,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
) -> LessonProgressSyncResponse:
    catalog = get_learning_catalog()
    completed_ids = set(request.completed_lesson_ids)
    unknown_ids = sorted(completed_ids - set(catalog.lessons_by_id))
    if unknown_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown lesson IDs: {', '.join(unknown_ids[:5])}",
        )

    completed_count = database.sync_completed_lesson_ids(
        user_id=current_user.user_id,
        lesson_ids=completed_ids,
    )
    progression = catalog.progression(database.completed_lesson_ids(user_id=current_user.user_id))
    return LessonProgressSyncResponse(
        completed_count=completed_count,
        course_level=str(progression["course_level"]),
        stage_number=int(progression["stage_number"]),
        current_lesson_id=str(progression["current_lesson_id"]),
    )


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
    evaluation_snapshot = build_lesson_evaluation_snapshot(
        database=database,
        catalog=get_learning_catalog(),
        user_id=current_user.user_id,
        lesson_id=lesson_id,
        state=request.state,
        generated_lesson=request.generated_lesson,
        messages=request.messages,
    )
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
            evaluation_snapshot=evaluation_snapshot,
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


@app.get("/me/vocabulary-practices", response_model=VocabularyPracticesResponse)
async def list_vocabulary_practices(
    limit: int = 100,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
) -> VocabularyPracticesResponse:
    practices = database.list_vocabulary_practices(
        user_id=current_user.user_id,
        limit=min(max(limit, 1), 500),
    )
    return VocabularyPracticesResponse(practices=[_vocabulary_practice_summary(row) for row in practices])


@app.get("/me/vocabulary-practices/{practice_id}", response_model=VocabularyPracticeResponse)
async def get_vocabulary_practice(
    practice_id: str,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
) -> VocabularyPracticeResponse:
    practice = database.get_vocabulary_practice(user_id=current_user.user_id, practice_id=practice_id)
    if practice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vocabulary practice not found.")
    return _vocabulary_practice_response(practice)


@app.post("/me/vocabulary-practices", response_model=VocabularyPracticeResponse)
async def create_vocabulary_practice(
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> VocabularyPracticeResponse:
    progression, selected_targets = select_practice_targets(
        database=database,
        catalog=get_learning_catalog(),
        user_id=current_user.user_id,
    )
    practice = database.create_vocabulary_practice(
        user_id=current_user.user_id,
        progression=progression,
        selected_targets=selected_targets,
        model=settings.vocabulary_interactor_model,
        prompt_version="vocabulary_interactor_v1",
    )
    try:
        quiz = await generate_vocabulary_quiz(
            settings,
            practice_id=practice.id,
            progression=progression,
            selected_targets=selected_targets,
            model=settings.vocabulary_interactor_model,
            reasoning_effort=settings.vocabulary_interactor_reasoning_effort,
        )
        validate_vocabulary_quiz(quiz, selected_targets)
        practice = database.activate_vocabulary_practice(
            user_id=current_user.user_id,
            practice_id=practice.id,
            quiz=quiz,
        )
    except ValueError as error:
        database.fail_vocabulary_practice(user_id=current_user.user_id, practice_id=practice.id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    except Exception:
        database.fail_vocabulary_practice(user_id=current_user.user_id, practice_id=practice.id)
        raise
    return _vocabulary_practice_response(practice)


@app.post("/me/vocabulary-practices/{practice_id}/messages", response_model=VocabularyPracticeResponse)
async def send_vocabulary_practice_message(
    practice_id: str,
    request: VocabularyPracticeMessageRequest,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> VocabularyPracticeResponse:
    practice = database.get_vocabulary_practice(user_id=current_user.user_id, practice_id=practice_id)
    if practice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vocabulary practice not found.")
    if len(practice.messages) >= 500:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Vocabulary practice chat limit reached.")
    try:
        response = await send_vocabulary_message(
            settings,
            practice_id=practice.id,
            context=vocabulary_interactor_context(practice),
            latest_user_message=request.latest_user_message,
            model=settings.vocabulary_interactor_model,
            reasoning_effort=settings.vocabulary_interactor_reasoning_effort,
        )
        validate_vocabulary_interaction(response)
        practice = database.append_vocabulary_interaction(
            user_id=current_user.user_id,
            practice_id=practice_id,
            user_text=request.latest_user_message,
            assistant_response=response,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _vocabulary_practice_response(practice)


@app.post("/me/vocabulary-practices/{practice_id}/next", response_model=VocabularyPracticeResponse)
async def advance_vocabulary_practice(
    practice_id: str,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
) -> VocabularyPracticeResponse:
    try:
        practice = database.advance_vocabulary_practice(
            user_id=current_user.user_id,
            practice_id=practice_id,
        )
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _vocabulary_practice_response(practice)


@app.post("/me/vocabulary-practices/{practice_id}/abandon", response_model=VocabularyPracticeResponse)
async def abandon_vocabulary_practice(
    practice_id: str,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
) -> VocabularyPracticeResponse:
    try:
        practice = database.abandon_vocabulary_practice(
            user_id=current_user.user_id,
            practice_id=practice_id,
        )
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _vocabulary_practice_response(practice)


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


def _vocabulary_practice_summary(row: VocabularyPracticeSession) -> VocabularyPracticeSummary:
    return VocabularyPracticeSummary(
        id=row.id,
        course_level=row.course_level,
        stage_number=row.stage_number,
        status=row.status,
        current_question_index=int(row.state.get("current_question_index", 0)),
        answered_count=len(row.state.get("answered_question_ids") or []),
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )


def _vocabulary_practice_response(row: VocabularyPracticeSession) -> VocabularyPracticeResponse:
    public_quiz: dict | None = None
    if row.quiz is not None:
        public_quiz = {
            "opening_text": row.quiz.get("opening_text"),
            "questions": [
                {
                    "id": question.get("id"),
                    "sentence_en": question.get("sentence_en"),
                }
                for question in row.quiz.get("questions", [])
            ],
        }
    return VocabularyPracticeResponse(
        **_vocabulary_practice_summary(row).model_dump(),
        progress_cutoff_absolute_day=row.progress_cutoff_absolute_day,
        quiz=public_quiz,
        state=row.state,
        messages=row.messages,
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
