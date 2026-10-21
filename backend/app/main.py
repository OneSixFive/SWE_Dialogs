from __future__ import annotations

import asyncio
import base64
import html
import json
import logging
import time as monotonic_time
from datetime import UTC, date, datetime, time, timedelta
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import httpx
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .auth import CurrentUser, get_database, get_settings, issue_session_token, require_user, verify_apple_identity_token
from .config import Settings
from .db import Database, LessonArtifact, LessonSession, LessonSessionConflict, VocabularyPracticeSession
from .evaluation_worker import evaluation_worker_loop
from .gemini_client import generate_wav
from .lesson_audio_worker import lesson_audio_worker_loop
from .lesson_artifacts import (
    artifact_audio_identity,
    lesson_content_hash,
    lesson_recipe,
    shared_audio_relative_path,
)
from .learning_catalog import get_learning_catalog
from .learning_service import (
    build_lesson_evaluation_snapshot,
    build_translation_lookup_evaluation_snapshot,
    select_practice_targets,
    validate_vocabulary_interaction,
    validate_vocabulary_quiz,
    vocabulary_interactor_context,
)
from .models import (
    AppleAuthRequest,
    AppleAuthResponse,
    LessonGenerateRequest,
    LessonArtifactResolveRequest,
    LessonArtifactResolveResponse,
    LessonArtifactSummary,
    LessonArtifactAudioSummary,
    LessonMessageRequest,
    LessonProgressSyncRequest,
    LessonProgressSyncResponse,
    LessonRegenerationRequest,
    LessonRegenerationResponse,
    LessonSessionResetRequest,
    LessonSessionResponse,
    LessonSessionsResponse,
    LessonSessionSummary,
    LessonSessionUpsertRequest,
    LessonAudioStatusResponse,
    TTSRequest,
    UserSummary,
    VocabularyPracticeMessageRequest,
    VocabularyPracticeResponse,
    VocabularyPracticesResponse,
    VocabularyPracticeSummary,
    TranslationLookupRequest,
)
from .openai_client import (
    generate_lesson,
    generator_prompt_sources,
    generate_vocabulary_quiz,
    send_lesson_message,
    send_speaker_turn,
    send_vocabulary_message,
)
from .speaking_service import (
    SPEAKER_LEARNER_TURNS,
    SpeakingContextError,
    SpeakingSessionLimitError,
    SpeakingSessionRegistry,
    SpeakingTurnError,
    build_speaker_instructions,
    project_reference_dialogue,
    project_speaking_lesson_context,
)
from .speech_clients import (
    MAX_TURN_AUDIO_SECONDS,
    MIN_TURN_AUDIO_SECONDS,
    SPEAKER_PCM_SAMPLE_RATE,
    SpeechProviderError,
    open_speech_stream,
    speech_usage_event,
    transcribe_learner_audio,
    wav_duration_seconds,
)


MAX_LESSON_AUDIO_BYTES = 25 * 1024 * 1024
MAX_SPEAKING_TURN_AUDIO_BYTES = 4 * 1024 * 1024
MAX_SPEAKER_TEXT_CHARACTERS = 1_200
logger = logging.getLogger("uvicorn.error")


def _artifact_audio_file_path(settings: Settings, *, content_hash: str, relative_path: str) -> Path:
    expected = shared_audio_relative_path(content_hash)
    if Path(relative_path) != expected:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lesson audio metadata is invalid.")
    root = settings.shared_audio_directory or (settings.database_path.parent / "shared_lesson_audio")
    return root / expected


speaking_sessions = SpeakingSessionRegistry()
USAGE_DASHBOARD_ROLES = (
    "Generator",
    "Interactor",
    "Vocabulary Quiz",
    "Vocabulary Interactor",
    "Evaluator",
    "Speaking",
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    workers: list[asyncio.Task[None]] = []
    try:
        settings = get_settings()
        database = get_database()
        if settings.evaluation_worker_enabled:
            workers.append(asyncio.create_task(evaluation_worker_loop(database, settings)))
        if settings.lesson_audio_worker_enabled:
            workers.append(asyncio.create_task(lesson_audio_worker_loop(database, settings)))
    except RuntimeError:
        # Local contract tests can construct the app without production secrets.
        workers = []
    try:
        yield
    finally:
        for worker in workers:
            worker.cancel()
        for worker in workers:
            with suppress(asyncio.CancelledError):
                await worker


app = FastAPI(title="Svenska Backend", version="0.2.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "svenska-backend"}


def require_usage_dashboard_token(
    token: str | None = Query(default=None),
    x_dashboard_token: str | None = Header(default=None, alias="X-Dashboard-Token"),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.usage_dashboard_token
    if not expected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usage dashboard is disabled.")
    supplied = token or x_dashboard_token
    if supplied != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid dashboard token.")


@app.get("/admin/usage", response_class=HTMLResponse)
async def usage_dashboard(_: None = Depends(require_usage_dashboard_token)) -> HTMLResponse:
    return HTMLResponse(_usage_dashboard_html())


@app.get("/admin/usage/data")
async def usage_dashboard_data(
    start: str | None = None,
    end: str | None = None,
    role: list[str] = Query(default=[]),
    _: None = Depends(require_usage_dashboard_token),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> dict:
    start_dt, end_dt = _usage_period(start, end)
    summary = database.usage_dashboard_summary(
        start_time=_dashboard_iso(start_dt),
        end_time=_dashboard_iso(end_dt),
        roles=role,
    )
    actual_cost = await _openai_org_actual_cost_usd(settings, start_dt, end_dt)
    payload = {
        "start_time": summary.start_time,
        "end_time": summary.end_time,
        "roles": summary.roles,
        "totals": summary.totals,
        "users": summary.users,
        "user_models": summary.user_models,
        "role_totals": summary.role_totals,
        "events": summary.events,
        "openai_org_actual_cost_usd": actual_cost,
        "available_roles": list(USAGE_DASHBOARD_ROLES),
    }
    return payload


@app.get("/admin/audio/metrics")
async def lesson_audio_metrics(
    _: None = Depends(require_usage_dashboard_token),
    database: Database = Depends(get_database),
) -> dict:
    return database.lesson_audio_metrics()


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


@app.post("/me/lesson-sessions/{lesson_id}/speaking/sessions", status_code=status.HTTP_201_CREATED)
async def start_speaking_session(
    lesson_id: str,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    if not settings.elevenlabs_api_key:
        logger.warning("speaking_unavailable reason=missing_elevenlabs_api_key")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Speaking practice is temporarily unavailable.",
        )
    lesson = get_learning_catalog().lesson(lesson_id)
    if lesson is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curriculum lesson not found.")
    session = database.get_lesson_session(user_id=current_user.user_id, lesson_id=lesson_id)
    if session is None or session.generated_lesson is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generate and synchronize this lesson before starting Speaking practice.",
        )
    try:
        instructions = build_speaker_instructions(lesson, session.generated_lesson)
        scenario = project_speaking_lesson_context(lesson)["scenario"]
    except (SpeakingContextError, OSError) as error:
        logger.warning(
            "speaking_context_invalid user_id=%s lesson_id=%s error_type=%s",
            current_user.user_id,
            lesson_id,
            type(error).__name__,
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stored lesson content is invalid.") from error

    try:
        lease = speaking_sessions.begin(
            current_user.user_id,
            lesson_id=lesson_id,
            instructions=instructions,
            transcription_context=f"Samtalsövning: {scenario}",
            timeout_seconds=settings.speaking_session_timeout_seconds,
            cooldown_seconds=settings.speaking_start_cooldown_seconds,
            window_seconds=settings.speaking_start_window_seconds,
            max_starts_per_window=settings.speaking_max_starts_per_window,
        )
    except SpeakingSessionLimitError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=str(error),
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    logger.info(
        "speaking_session_started user_id=%s lesson_id=%s session_id=%s",
        current_user.user_id,
        lesson_id,
        lease.session_id,
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "session_id": lease.session_id,
            "timeout_seconds": settings.speaking_session_timeout_seconds,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/me/lesson-sessions/{lesson_id}/speaking/sessions/{session_id}/turns")
async def create_speaking_turn(
    lesson_id: str,
    session_id: str,
    audio: bytes = Body(default=b"", media_type="audio/wav"),
    content_type: str | None = Header(default=None, alias="Content-Type"),
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """Run one Speaker turn: transcribe the learner, ask the Speaker, then stream its speech as NDJSON."""
    try:
        conversation = speaking_sessions.claim_turn(current_user.user_id, lesson_id, session_id)
    except SpeakingTurnError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error

    timings: dict[str, int] = {}
    try:
        transcript: str | None = None
        if conversation.is_opening:
            if audio:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="The opening turn takes no audio.",
                )
        else:
            if not content_type or content_type.split(";", 1)[0].strip().lower() != "audio/wav":
                raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Expected audio/wav.")
            if len(audio) > MAX_SPEAKING_TURN_AUDIO_BYTES:
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Recording is too long.")
            try:
                audio_seconds = wav_duration_seconds(audio)
            except ValueError as error:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
            if audio_seconds < MIN_TURN_AUDIO_SECONDS:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Recording is too short.")
            if audio_seconds > MAX_TURN_AUDIO_SECONDS:
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Recording is too long.")
            transcription = await transcribe_learner_audio(
                settings,
                wav=audio,
                context=conversation.transcription_context,
            )
            timings["stt_ms"] = transcription.elapsed_ms
            database.record_openai_usage(
                speech_usage_event(
                    settings,
                    user_id=current_user.user_id,
                    lesson_id=lesson_id,
                    request_name="speaker_transcription",
                    model=settings.speaker_transcription_model,
                    elapsed_ms=transcription.elapsed_ms,
                    audio_seconds=transcription.audio_seconds,
                    request_id=transcription.request_id,
                    raw_usage=transcription.raw_usage,
                )
            )
            if not transcription.text:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="No speech was detected. Please try again.",
                )
            transcript = transcription.text[:MAX_SPEAKER_TEXT_CHARACTERS]

        started = monotonic_time.perf_counter()
        reply = await send_speaker_turn(
            settings,
            user_id=current_user.user_id,
            lesson_id=lesson_id,
            instructions=conversation.instructions,
            prior_messages=list(conversation.messages),
            speaker_state=conversation.state(),
            latest_learner_transcript=transcript,
            usage_recorder=database.record_openai_usage,
        )
        timings["llm_ms"] = int((monotonic_time.perf_counter() - started) * 1000)
        say = str(reply.get("say") or "").strip()
        learner_turn = "opening" if conversation.is_opening else str(reply.get("learner_turn"))
        correcting = reply.get("correcting") is True and not conversation.is_opening
        if not say or len(say) > MAX_SPEAKER_TEXT_CHARACTERS or learner_turn not in SPEAKER_LEARNER_TURNS:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The tutor reply was invalid.")

        stream = await open_speech_stream(settings, text=say)
        timings["tts_first_audio_ms"] = stream.first_audio_ms
    except SpeechProviderError as error:
        speaking_sessions.release_turn(session_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The speech service failed. Please try again.",
        ) from error
    except BaseException:
        speaking_sessions.release_turn(session_id)
        raise

    # The turn is committed only once the learner is certain to hear the reply.
    turn_index = sum(1 for message in conversation.messages if message["role"] == "assistant")
    conversation.apply_turn(transcript=transcript, learner_turn=learner_turn, correcting=correcting, say=say)
    completed = conversation.completed
    database.record_speaking_turn(
        user_id=current_user.user_id,
        lesson_id=lesson_id,
        session_id=session_id,
        turn_index=turn_index,
        learner_transcript=transcript,
        learner_turn=learner_turn,
        correcting=correcting,
        speaker_text=say,
        counted_replies=conversation.counted_replies,
        completed=completed,
    )
    logger.info(
        "speaking_turn user_id=%s lesson_id=%s session_id=%s turn=%s learner_turn=%s correcting=%s "
        "counted=%s completed=%s stt_ms=%s llm_ms=%s tts_first_audio_ms=%s",
        current_user.user_id,
        lesson_id,
        session_id,
        turn_index,
        learner_turn,
        correcting,
        conversation.counted_replies,
        completed,
        timings.get("stt_ms"),
        timings.get("llm_ms"),
        timings.get("tts_first_audio_ms"),
    )

    async def ndjson_turn():
        started_streaming = monotonic_time.perf_counter()
        try:
            yield _ndjson_line(
                {
                    "type": "turn",
                    "transcript": transcript,
                    "say": say,
                    "practice_complete": completed,
                    "sample_rate": SPEAKER_PCM_SAMPLE_RATE,
                }
            )
            async for chunk in stream.pcm_chunks():
                yield _ndjson_line({"type": "audio", "pcm": base64.b64encode(chunk).decode("ascii")})
            yield _ndjson_line({"type": "done"})
        except Exception as error:
            logger.warning(
                "speaking_turn_stream_failed user_id=%s lesson_id=%s session_id=%s error_type=%s",
                current_user.user_id,
                lesson_id,
                session_id,
                type(error).__name__,
            )
            yield _ndjson_line({"type": "error", "detail": "The tutor audio was interrupted."})
        finally:
            await stream.aclose()
            database.record_openai_usage(
                speech_usage_event(
                    settings,
                    user_id=current_user.user_id,
                    lesson_id=lesson_id,
                    request_name="speaker_tts",
                    model=settings.speaker_tts_model,
                    elapsed_ms=stream.first_audio_ms
                    + int((monotonic_time.perf_counter() - started_streaming) * 1000),
                    characters=len(say),
                )
            )
            speaking_sessions.release_turn(session_id)
            if completed:
                speaking_sessions.finish(current_user.user_id, lesson_id, session_id)

    return StreamingResponse(
        ndjson_turn(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store"},
    )


@app.delete(
    "/me/lesson-sessions/{lesson_id}/speaking/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def end_speaking_session(
    lesson_id: str,
    session_id: str,
    current_user: CurrentUser = Depends(require_user),
) -> Response:
    speaking_sessions.finish(current_user.user_id, lesson_id, session_id)
    logger.info("speaking_session_ended user_id=%s lesson_id=%s session_id=%s", current_user.user_id, lesson_id, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _ndjson_line(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


@app.get("/me/lesson-sessions/{lesson_id}/audio")
async def get_lesson_audio(
    lesson_id: str,
    expected_content_hash: str | None = None,
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> Response:
    session = database.get_lesson_session(user_id=current_user.user_id, lesson_id=lesson_id)
    if session is not None and session.lesson_artifact_id:
        artifact = database.lesson_artifact_for_user(
            artifact_id=session.lesson_artifact_id, user_id=current_user.user_id
        )
        if artifact is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lesson artifact is unavailable.")
        _, content_hash, recipe = artifact_audio_identity(settings, artifact.generated_lesson)
        audio = database.get_artifact_audio(
            lesson_artifact_id=artifact.id, audio_recipe_fingerprint=recipe.fingerprint
        )
        if audio is None or audio.content_hash != content_hash:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson audio not found.")
        file_path = _artifact_audio_file_path(
            settings, content_hash=content_hash, relative_path=audio.relative_file_path
        )
        if not file_path.is_file():
            database.delete_artifact_audio(
                lesson_artifact_id=artifact.id, audio_recipe_fingerprint=recipe.fingerprint
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson audio not found.")
        if expected_content_hash is not None and expected_content_hash != content_hash:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lesson generation changed.")
        etag = f'"{content_hash}"'
        if if_none_match == etag:
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
        audio_data = file_path.read_bytes()
        if len(audio_data) != audio.byte_count:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lesson audio is incomplete.")
        return Response(
            content=audio_data,
            media_type=audio.content_type,
            headers={
                "Content-Length": str(audio.byte_count),
                "ETag": etag,
                "X-Lesson-Audio-Content-Hash": content_hash,
            },
        )

    audio = database.get_lesson_audio(user_id=current_user.user_id, lesson_id=lesson_id)
    if audio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson audio not found.")
    identity = database.current_lesson_audio_identity(user_id=current_user.user_id, lesson_id=lesson_id)
    if identity is None or audio.content_hash != identity[1]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lesson generation changed.")
    if expected_content_hash is not None and expected_content_hash != audio.content_hash:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lesson generation changed.")
    etag = f'"{audio.content_hash}"'
    headers = {
        "Content-Length": str(audio.byte_count),
        "ETag": etag,
        "X-Lesson-Audio-Content-Hash": audio.content_hash,
    }
    if if_none_match == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    logger.info(
        "lesson_audio_downloaded user_id=%s lesson_id=%s content_hash=%s bytes=%s",
        current_user.user_id, lesson_id, audio.content_hash[:12], audio.byte_count,
    )
    return Response(
        content=audio.audio_data,
        media_type=audio.content_type,
        headers=headers,
    )


@app.get(
    "/me/lesson-sessions/{lesson_id}/audio/status",
    response_model=LessonAudioStatusResponse,
)
async def get_lesson_audio_status(
    lesson_id: str,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> LessonAudioStatusResponse:
    session = database.get_lesson_session(user_id=current_user.user_id, lesson_id=lesson_id)
    if session is not None and session.lesson_artifact_id:
        artifact = database.lesson_artifact_for_user(
            artifact_id=session.lesson_artifact_id, user_id=current_user.user_id
        )
        if artifact is None:
            return LessonAudioStatusResponse(lesson_id=lesson_id, status="missing", retryable=False)
        _, content_hash, recipe = artifact_audio_identity(settings, artifact.generated_lesson)
        audio_status, job, audio = database.artifact_audio_status(
            artifact=artifact,
            content_hash=content_hash,
            audio_recipe_fingerprint=recipe.fingerprint,
        )
        if audio is not None:
            file_path = _artifact_audio_file_path(
                settings, content_hash=content_hash, relative_path=audio.relative_file_path
            )
            if not file_path.is_file():
                database.delete_artifact_audio(
                    lesson_artifact_id=artifact.id, audio_recipe_fingerprint=recipe.fingerprint
                )
                audio_status, audio = "missing", None
        return LessonAudioStatusResponse(
            lesson_id=lesson_id,
            content_hash=content_hash,
            status="ready" if audio is not None else audio_status,
            attempt_count=job.attempt_count if job else 0,
            retryable=audio_status in {"missing", "failed"},
            updated_at=audio.updated_at if audio is not None else (job.updated_at if job else None),
            error_code=job.last_error_code if job and audio_status == "failed" else None,
        )

    audio_status, content_hash, job = database.lesson_audio_status(
        user_id=current_user.user_id,
        lesson_id=lesson_id,
    )
    public_status = "ready" if audio_status == "ready" else audio_status
    return LessonAudioStatusResponse(
        lesson_id=lesson_id,
        content_hash=content_hash,
        status=public_status,
        attempt_count=job.attempt_count if job else 0,
        retryable=public_status in {"missing", "failed"},
        updated_at=job.updated_at if job else None,
        error_code=job.last_error_code if job and public_status == "failed" else None,
    )


@app.post(
    "/me/lesson-sessions/{lesson_id}/audio/generate",
    response_model=LessonAudioStatusResponse,
)
async def generate_lesson_audio(
    lesson_id: str,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    session = database.get_lesson_session(user_id=current_user.user_id, lesson_id=lesson_id)
    if session is not None and session.lesson_artifact_id:
        artifact = database.lesson_artifact_for_user(
            artifact_id=session.lesson_artifact_id, user_id=current_user.user_id
        )
        if artifact is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lesson artifact is unavailable.")
        dialogue_hash, content_hash, recipe = artifact_audio_identity(settings, artifact.generated_lesson)
        existing = database.get_artifact_audio(
            lesson_artifact_id=artifact.id, audio_recipe_fingerprint=recipe.fingerprint
        )
        if existing is not None:
            file_path = _artifact_audio_file_path(
                settings, content_hash=content_hash, relative_path=existing.relative_file_path
            )
            if not file_path.is_file():
                database.delete_artifact_audio(
                    lesson_artifact_id=artifact.id, audio_recipe_fingerprint=recipe.fingerprint
                )
        try:
            job, audio = database.request_artifact_audio_job(
                artifact=artifact,
                requested_by_user_id=current_user.user_id,
                content_hash=content_hash,
                dialogue_text_hash=dialogue_hash,
                audio_recipe_fingerprint=recipe.fingerprint,
                model=settings.lesson_tts_model,
                voice_config_version=settings.lesson_tts_voice_config_version,
                max_queued_per_user=settings.lesson_audio_max_queued_per_user,
                retry_cooldown_seconds=settings.lesson_audio_retry_cooldown_seconds,
            )
        except OverflowError as error:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(error)
            ) from error
        if audio is not None:
            payload = LessonAudioStatusResponse(
                lesson_id=lesson_id, content_hash=content_hash, status="ready",
                retryable=False, updated_at=audio.updated_at,
            )
            return JSONResponse(status_code=status.HTTP_200_OK, content=payload.model_dump())
        if job is None:
            raise RuntimeError("Artifact audio request returned neither audio nor a job.")
        payload = LessonAudioStatusResponse(
            lesson_id=lesson_id, content_hash=content_hash, status=job.status,
            attempt_count=job.attempt_count, retryable=job.status == "failed",
            updated_at=job.updated_at,
            error_code=job.last_error_code if job.status == "failed" else None,
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED if job.status in {"pending", "running"} else status.HTTP_429_TOO_MANY_REQUESTS,
            content=payload.model_dump(),
        )

    try:
        job, audio = database.request_lesson_audio_job(
            user_id=current_user.user_id,
            lesson_id=lesson_id,
            max_queued_per_user=settings.lesson_audio_max_queued_per_user,
            retry_cooldown_seconds=settings.lesson_audio_retry_cooldown_seconds,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except OverflowError as error:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(error)) from error

    if audio is not None:
        payload = LessonAudioStatusResponse(
            lesson_id=lesson_id, content_hash=audio.content_hash, status="ready",
            attempt_count=0, retryable=False, updated_at=audio.updated_at,
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=payload.model_dump())
    if job is None:
        raise RuntimeError("Audio generation request returned neither audio nor a job.")
    if job.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Please wait before retrying lesson audio.",
            headers={"Retry-After": str(settings.lesson_audio_retry_cooldown_seconds)},
        )
    logger.info(
        "lesson_audio_requested user_id=%s lesson_id=%s content_hash=%s job_id=%s attempt=%s model=%s voice_config=%s",
        current_user.user_id, lesson_id, job.content_hash[:12], job.id, job.attempt_count,
        job.model, job.voice_config_version,
    )
    payload = LessonAudioStatusResponse(
        lesson_id=lesson_id,
        content_hash=job.content_hash,
        status=job.status,
        attempt_count=job.attempt_count,
        retryable=False,
        updated_at=job.updated_at,
    )
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=payload.model_dump())


@app.put("/me/lesson-sessions/{lesson_id}/audio")
async def put_lesson_audio(
    lesson_id: str,
    audio_data: bytes = Body(..., media_type="audio/wav"),
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
) -> dict[str, object]:
    if not audio_data:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Audio data is empty.")
    if len(audio_data) > MAX_LESSON_AUDIO_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Audio file is too large.")
    if not audio_data.startswith(b"RIFF"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Audio must be a WAV file.")

    audio = database.store_lesson_audio(
        user_id=current_user.user_id,
        lesson_id=lesson_id,
        audio_data=audio_data,
        content_type="audio/wav",
    )
    if audio is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lesson must be generated before audio can be stored.",
        )
    return {
        "lesson_id": audio.lesson_id,
        "has_audio": True,
        "byte_count": audio.byte_count,
        "generated_at": audio.generated_at,
        "updated_at": audio.updated_at,
        "content_hash": audio.content_hash,
    }


@app.put("/me/lesson-sessions/{lesson_id}", response_model=LessonSessionResponse)
async def put_lesson_session(
    lesson_id: str,
    request: LessonSessionUpsertRequest,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
) -> LessonSessionResponse:
    _validate_lesson_session_payload(lesson_id, request)
    stored_generated_lesson = request.generated_lesson
    if request.lesson_artifact_id is not None:
        artifact = database.lesson_artifact_for_user(
            artifact_id=request.lesson_artifact_id, user_id=current_user.user_id
        )
        if artifact is None or artifact.lesson_id != lesson_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Lesson artifact is not available.")
        current_session = database.get_lesson_session(user_id=current_user.user_id, lesson_id=lesson_id)
        is_existing_pin = (
            current_session is not None
            and current_session.lesson_artifact_id == request.lesson_artifact_id
        )
        if artifact.invalidated_at is not None and not is_existing_pin:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lesson artifact is no longer current.")
        if (
            request.generated_lesson is None
            or request.generated_lesson.get("artifact_id") != artifact.id
            or lesson_content_hash(request.generated_lesson) != artifact.lesson_content_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Generated lesson must match the referenced artifact.",
            )
        stored_generated_lesson = artifact.generated_lesson
    evaluation_snapshot = build_lesson_evaluation_snapshot(
        database=database,
        catalog=get_learning_catalog(),
        user_id=current_user.user_id,
        lesson_id=lesson_id,
        state=request.state,
        generated_lesson=stored_generated_lesson,
        messages=request.messages,
    )
    try:
        row = database.upsert_lesson_session(
            user_id=current_user.user_id,
            lesson_id=lesson_id,
            state=request.state,
            generated_lesson=stored_generated_lesson,
            messages=request.messages,
            chat_summary=request.chat_summary,
            client_updated_at=request.client_updated_at,
            base_server_updated_at=request.base_server_updated_at,
            reset_generation=request.reset_generation,
            lesson_artifact_id=request.lesson_artifact_id,
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
        model=settings.vocabulary_quiz_model,
        prompt_version="vocabulary_interactor_v1",
    )
    try:
        quiz = await generate_vocabulary_quiz(
            settings,
            user_id=current_user.user_id,
            practice_id=practice.id,
            progression=progression,
            selected_targets=selected_targets,
            model=settings.vocabulary_quiz_model,
            reasoning_effort=settings.vocabulary_quiz_reasoning_effort,
            usage_recorder=database.record_openai_usage,
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
    _record_translation_lookup_if_present(
        database=database,
        user_id=current_user.user_id,
        lookup=request.translation_lookup,
        source_kind="vocabulary_practice",
        source_id=practice_id,
    )
    try:
        response = await send_vocabulary_message(
            settings,
            user_id=current_user.user_id,
            practice_id=practice.id,
            context=vocabulary_interactor_context(practice),
            latest_user_message=request.latest_user_message,
            model=settings.vocabulary_interactor_model,
            reasoning_effort=settings.vocabulary_interactor_reasoning_effort,
            usage_recorder=database.record_openai_usage,
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
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        return await generate_lesson(
            settings,
            user_id=current_user.user_id,
            payload=request.payload,
            model=request.model,
            reasoning_effort=request.reasoning_effort,
            usage_recorder=database.record_openai_usage,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error


def _artifact_resolve_response(
    *,
    resolution: str,
    artifact: LessonArtifact,
    database: Database,
    settings: Settings,
) -> LessonArtifactResolveResponse:
    _, content_hash, recipe = artifact_audio_identity(settings, artifact.generated_lesson)
    audio_status, _, audio = database.artifact_audio_status(
        artifact=artifact,
        content_hash=content_hash,
        audio_recipe_fingerprint=recipe.fingerprint,
    )
    return LessonArtifactResolveResponse(
        resolution=resolution,
        artifact=LessonArtifactSummary(
            id=artifact.id,
            lesson_id=artifact.lesson_id,
            scope=artifact.scope,
            recipe_fingerprint=artifact.recipe_fingerprint,
            generated_lesson=artifact.generated_lesson,
        ),
        audio=LessonArtifactAudioSummary(
            status="ready" if audio is not None else audio_status,
            content_hash=content_hash,
        ),
    )


def _lesson_regeneration_response(
    *,
    operation_key: str,
    artifact: LessonArtifact,
    session: LessonSession,
    database: Database,
    settings: Settings,
) -> LessonRegenerationResponse:
    resolved = _artifact_resolve_response(
        resolution="generated", artifact=artifact, database=database, settings=settings
    )
    return LessonRegenerationResponse(
        operation_key=operation_key,
        status="succeeded",
        artifact=resolved.artifact,
        session=_lesson_session_response(session),
        audio=resolved.audio,
    )


@app.post(
    "/me/lesson-sessions/{lesson_id}/regenerate",
    response_model=LessonRegenerationResponse,
)
async def regenerate_lesson_session(
    lesson_id: str,
    request: LessonRegenerationRequest,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> LessonRegenerationResponse | JSONResponse:
    if not settings.shared_lesson_artifacts_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lesson artifacts are temporarily unavailable.",
        )
    catalog_lesson = get_learning_catalog().lesson(lesson_id)
    if catalog_lesson is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curriculum lesson not found.")
    shared_prompt, generator_prompt = generator_prompt_sources()
    recipe = lesson_recipe(
        settings,
        lesson_id=catalog_lesson.lesson_id,
        payload=catalog_lesson.payload,
        shared_base_prompt=shared_prompt,
        generator_prompt=generator_prompt,
    )
    try:
        job, claimed = database.begin_lesson_generation(
            lesson_id=catalog_lesson.lesson_id,
            recipe_fingerprint=recipe.fingerprint,
            recipe=recipe.document,
            scope="private",
            requested_by_user_id=current_user.user_id,
            lease_seconds=max(int(settings.openai_timeout_seconds) + 30, 300),
            operation_key=request.operation_key,
            expected_server_updated_at=request.base_server_updated_at,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    if not claimed:
        if job.status == "superseded":
            current = database.get_lesson_session(
                user_id=current_user.user_id, lesson_id=lesson_id
            )
            if current is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "message": "Lesson session has newer server state.",
                        "current": _lesson_session_response(current).model_dump(by_alias=True),
                    },
                )
        if job.status == "succeeded" and job.artifact_id:
            artifact = database.lesson_artifact_for_user(
                artifact_id=job.artifact_id, user_id=current_user.user_id
            )
            session = database.get_lesson_session(
                user_id=current_user.user_id, lesson_id=lesson_id
            )
            if (
                artifact is not None
                and session is not None
                and session.lesson_artifact_id == artifact.id
            ):
                return _lesson_regeneration_response(
                    operation_key=request.operation_key,
                    artifact=artifact,
                    session=session,
                    database=database,
                    settings=settings,
                )
        payload = LessonRegenerationResponse(
            operation_key=request.operation_key,
            status=job.status,
            retry_after_seconds=1 if job.status == "running" else None,
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=payload.model_dump(),
        )

    metadata: dict[str, str | None] = {}
    try:
        generated = await generate_lesson(
            settings,
            user_id=current_user.user_id,
            payload=catalog_lesson.payload,
            model=settings.lesson_generator_model,
            reasoning_effort=settings.lesson_generator_reasoning_effort,
            usage_recorder=database.record_openai_usage,
            response_metadata_recorder=metadata.update,
        )
        dialogue_hash, audio_content_hash, audio_recipe = artifact_audio_identity(settings, generated)
        artifact, session, _ = database.complete_lesson_regeneration(
            job=job,
            generated_lesson=generated,
            lesson_content_hash=lesson_content_hash(generated),
            requested_model=settings.lesson_generator_model,
            provider_model=metadata.get("provider_model"),
            reasoning_effort=settings.lesson_generator_reasoning_effort,
            provider_request_id=metadata.get("provider_request_id"),
            dialogue_text_hash=dialogue_hash,
            audio_content_hash=audio_content_hash,
            audio_recipe_fingerprint=audio_recipe.fingerprint,
            audio_model=settings.lesson_tts_model,
            voice_config_version=settings.lesson_tts_voice_config_version,
        )
    except LessonSessionConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Lesson session has newer server state.",
                "current": _lesson_session_response(error.current).model_dump(by_alias=True),
            },
        ) from error
    except Exception as error:
        database.fail_lesson_generation(
            job_id=job.id,
            attempt_count=job.attempt_count,
            error_code=type(error).__name__,
            error_summary=str(error) or "Lesson regeneration failed.",
        )
        raise
    logger.info(
        "lesson_regeneration_attached user_id=%s lesson_id=%s operation_key=%s artifact_id=%s",
        current_user.user_id, lesson_id, request.operation_key, artifact.id,
    )
    return _lesson_regeneration_response(
        operation_key=request.operation_key,
        artifact=artifact,
        session=session,
        database=database,
        settings=settings,
    )


@app.post("/lessons/artifacts/resolve", response_model=LessonArtifactResolveResponse)
async def resolve_lesson_artifact(
    request: LessonArtifactResolveRequest,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> LessonArtifactResolveResponse | JSONResponse:
    if not settings.shared_lesson_artifacts_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shared lesson artifacts are temporarily unavailable.",
        )
    catalog_lesson = get_learning_catalog().lesson(request.lesson_id)
    if catalog_lesson is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curriculum lesson not found.")
    shared_prompt, generator_prompt = generator_prompt_sources()
    recipe = lesson_recipe(
        settings,
        lesson_id=catalog_lesson.lesson_id,
        payload=catalog_lesson.payload,
        shared_base_prompt=shared_prompt,
        generator_prompt=generator_prompt,
    )
    if request.mode == "shared":
        existing = database.get_shared_lesson_artifact(
            lesson_id=catalog_lesson.lesson_id,
            recipe_fingerprint=recipe.fingerprint,
        )
        if existing is not None:
            logger.info(
                "lesson_artifact_cache_hit user_id=%s lesson_id=%s recipe=%s artifact_id=%s",
                current_user.user_id, request.lesson_id, recipe.fingerprint[:12], existing.id,
            )
            return _artifact_resolve_response(
                resolution="cache_hit", artifact=existing, database=database, settings=settings
            )

    job, claimed = database.begin_lesson_generation(
        lesson_id=catalog_lesson.lesson_id,
        recipe_fingerprint=recipe.fingerprint,
        recipe=recipe.document,
        scope=request.mode,
        requested_by_user_id=current_user.user_id,
        lease_seconds=max(int(settings.openai_timeout_seconds) + 30, 300),
    )
    if not claimed:
        if job.status == "succeeded" and job.artifact_id:
            artifact = database.lesson_artifact_for_user(
                artifact_id=job.artifact_id, user_id=current_user.user_id
            )
            if artifact is not None:
                return _artifact_resolve_response(
                    resolution="cache_hit", artifact=artifact, database=database, settings=settings
                )
        payload = LessonArtifactResolveResponse(
            resolution="queued", job_id=job.id, status=job.status, retry_after_seconds=1
        )
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=payload.model_dump())

    metadata: dict[str, str | None] = {}
    logger.info(
        "lesson_artifact_cache_miss user_id=%s lesson_id=%s scope=%s recipe=%s job_id=%s",
        current_user.user_id, request.lesson_id, request.mode, recipe.fingerprint[:12], job.id,
    )
    try:
        generated = await generate_lesson(
            settings,
            user_id=current_user.user_id,
            payload=catalog_lesson.payload,
            model=settings.lesson_generator_model,
            reasoning_effort=settings.lesson_generator_reasoning_effort,
            usage_recorder=database.record_openai_usage,
            response_metadata_recorder=metadata.update,
        )
        artifact = database.complete_lesson_generation(
            job=job,
            generated_lesson=generated,
            lesson_content_hash=lesson_content_hash(generated),
            requested_model=settings.lesson_generator_model,
            provider_model=metadata.get("provider_model"),
            reasoning_effort=settings.lesson_generator_reasoning_effort,
            provider_request_id=metadata.get("provider_request_id"),
        )
    except Exception as error:
        database.fail_lesson_generation(
            job_id=job.id,
            attempt_count=job.attempt_count,
            error_code=type(error).__name__,
            error_summary=str(error) or "Lesson generation failed.",
        )
        raise
    logger.info(
        "lesson_artifact_published user_id=%s lesson_id=%s scope=%s recipe=%s artifact_id=%s",
        current_user.user_id, request.lesson_id, request.mode, recipe.fingerprint[:12], artifact.id,
    )
    return _artifact_resolve_response(
        resolution="generated", artifact=artifact, database=database, settings=settings
    )


@app.get("/lessons/artifacts/jobs/{job_id}", response_model=LessonArtifactResolveResponse)
async def get_lesson_artifact_job(
    job_id: int,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> LessonArtifactResolveResponse:
    job = database.get_lesson_generation_job(job_id=job_id, user_id=current_user.user_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson generation job not found.")
    if job.status == "succeeded" and job.artifact_id:
        artifact = database.lesson_artifact_for_user(
            artifact_id=job.artifact_id, user_id=current_user.user_id
        )
        if artifact is not None:
            return _artifact_resolve_response(
                resolution="generated", artifact=artifact, database=database, settings=settings
            )
    return LessonArtifactResolveResponse(
        resolution="queued" if job.status == "running" else job.status,
        job_id=job.id,
        status=job.status,
        retry_after_seconds=1 if job.status == "running" else None,
    )


@app.post("/lessons/message")
async def lessons_message(
    request: LessonMessageRequest,
    current_user: CurrentUser = Depends(require_user),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> dict:
    _record_translation_lookup_if_present(
        database=database,
        user_id=current_user.user_id,
        lookup=request.translation_lookup,
        source_kind="lesson",
        source_id=str(request.payload.get("id") or ""),
    )
    try:
        return await send_lesson_message(
            settings,
            user_id=current_user.user_id,
            payload=request.payload,
            generated_lesson=request.generated_lesson,
            state=request.state,
            chat_history=request.chat_history,
            latest_user_message=request.latest_user_message,
            model=request.model,
            reasoning_effort=request.reasoning_effort,
            usage_recorder=database.record_openai_usage,
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
        has_audio=row.has_audio,
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
        lesson_artifact_id=row.lesson_artifact_id,
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


def _usage_period(start: str | None, end: str | None) -> tuple[datetime, datetime]:
    today = datetime.now(UTC).date()
    start_date = _parse_dashboard_date(start) if start else today.replace(day=1)
    end_date = _parse_dashboard_date(end) if end else today
    if end_date < start_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="End date cannot be before start date.")
    start_dt = datetime.combine(start_date, time.min, tzinfo=UTC)
    end_dt = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
    return start_dt, end_dt


def _parse_dashboard_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Dates must be YYYY-MM-DD.") from error


def _dashboard_iso(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


async def _openai_org_actual_cost_usd(settings: Settings, start_dt: datetime, end_dt: datetime) -> float | None:
    if not settings.openai_admin_key:
        return None
    headers = {"Authorization": f"Bearer {settings.openai_admin_key}"}
    params = {
        "start_time": int(start_dt.timestamp()),
        "end_time": int(end_dt.timestamp()),
        "bucket_width": "1d",
        "limit": 100,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get("https://api.openai.com/v1/organization/costs", headers=headers, params=params)
        if response.status_code < 200 or response.status_code > 299:
            return None
        payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        return None

    total = 0.0
    for bucket in payload.get("data") or []:
        for result in bucket.get("results") or []:
            amount = result.get("amount") or {}
            value = amount.get("value")
            if isinstance(value, int | float):
                total += float(value)
    return round(total, 6)


def _usage_dashboard_html() -> str:
    role_controls = "\n".join(
        f'<label><input type="checkbox" name="role" value="{html.escape(role)}" checked> {html.escape(role)}</label>'
        for role in USAGE_DASHBOARD_ROLES
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Svenska Usage</title>
  <style>
    :root {{ color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #f7f7f4; color: #191917; }}
    header, main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    header {{ display: flex; justify-content: space-between; gap: 16px; align-items: end; }}
    h1 {{ margin: 0; font-size: 28px; letter-spacing: 0; }}
    .muted {{ color: #66645d; font-size: 13px; }}
    .controls {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: end; margin-bottom: 18px; }}
    .controls label {{ display: grid; gap: 5px; font-size: 13px; color: #4b4a45; }}
    input[type="date"] {{ height: 36px; border: 1px solid #c9c7bd; border-radius: 6px; padding: 0 10px; background: white; }}
    button {{ height: 36px; border: 0; border-radius: 6px; padding: 0 14px; background: #23231f; color: white; cursor: pointer; }}
    .segmented {{ display: inline-flex; height: 36px; border: 1px solid #c9c7bd; border-radius: 6px; overflow: hidden; background: white; }}
    .segmented button {{ border-radius: 0; background: white; color: #23231f; border-right: 1px solid #c9c7bd; }}
    .segmented button:last-child {{ border-right: 0; }}
    .segmented button.active {{ background: #23231f; color: white; }}
    .role-grid {{ display: flex; flex-wrap: wrap; gap: 8px 14px; width: 100%; margin: 4px 0 10px; }}
    .role-grid label {{ display: flex; gap: 6px; align-items: center; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(140px, 1fr)); gap: 10px; margin-bottom: 18px; }}
    .metric, section {{ background: white; border: 1px solid #ddd9cd; border-radius: 8px; }}
    .metric {{ padding: 14px; }}
    .metric strong {{ display: block; font-size: 22px; margin-top: 4px; }}
    section {{ margin-bottom: 18px; overflow: hidden; }}
    h2 {{ font-size: 16px; margin: 0; padding: 14px; border-bottom: 1px solid #e7e4d9; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #eeece4; white-space: nowrap; }}
    th {{ color: #55524b; font-weight: 600; background: #fbfaf7; }}
    th.sortable {{ cursor: pointer; user-select: none; }}
    th.sortable::after {{ color: #8a877e; content: " ↆ"; font-size: 11px; }}
    th.sorted-asc::after {{ content: " ↑"; }}
    th.sorted-desc::after {{ content: " ↓"; }}
    td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    tfoot td {{ background: #fbfaf7; font-weight: 700; }}
    .empty {{ padding: 18px; color: #66645d; }}
    @media (max-width: 760px) {{
      header {{ display: block; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      section {{ overflow-x: auto; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Svenska Usage</h1>
      <div class="muted" id="periodLabel">Month to date</div>
    </div>
    <div class="muted">Per-user cost is estimated from recorded tokens. Organization actual is from OpenAI billing when configured.</div>
  </header>
  <main>
    <form class="controls" id="filters">
      <label>Start <input type="date" name="start"></label>
      <label>End <input type="date" name="end"></label>
      <label>Cost Basis
        <span class="segmented" aria-label="Cost basis">
          <button type="button" data-cost-basis="estimated" class="active">Estimated</button>
          <button type="button" data-cost-basis="actual">Actual</button>
        </span>
      </label>
      <div class="role-grid">{role_controls}</div>
      <button type="submit">Refresh</button>
    </form>
    <div class="metrics">
      <div class="metric"><span class="muted">Requests</span><strong id="requests">0</strong></div>
      <div class="metric"><span class="muted">Tokens</span><strong id="tokens">0</strong></div>
      <div class="metric"><span class="muted">Estimated Cost</span><strong id="estimated">$0.00</strong></div>
      <div class="metric"><span class="muted">OpenAI Actual</span><strong id="actual">n/a</strong></div>
      <div class="metric"><span class="muted">Cache Reads</span><strong id="cacheReads">0</strong></div>
      <div class="metric"><span class="muted">Cache Writes</span><strong id="cacheWrites">0</strong></div>
      <div class="metric"><span class="muted">Ordinary Input</span><strong id="ordinaryInput">0</strong></div>
      <div class="metric"><span class="muted">Net Cache Savings</span><strong id="cacheSavings">$0.00</strong></div>
    </div>
    <section><h2>Users by Model</h2><div id="users"></div></section>
    <section><h2>Roles and Models</h2><div id="roles"></div></section>
    <section><h2>Recent Requests</h2><div id="events"></div></section>
  </main>
  <script>
    const token = new URLSearchParams(location.search).get('token') || '';
    const form = document.getElementById('filters');
    const state = {{ data: null, costBasis: 'estimated', sort: {{ key: 'total', direction: 'desc' }} }};
    const today = new Date();
    const iso = d => d.toISOString().slice(0, 10);
    form.start.value = iso(new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 1)));
    form.end.value = iso(today);
    form.addEventListener('submit', event => {{ event.preventDefault(); load(); }});
    for (const button of document.querySelectorAll('[data-cost-basis]')) {{
      button.addEventListener('click', () => {{
        state.costBasis = button.dataset.costBasis;
        for (const item of document.querySelectorAll('[data-cost-basis]')) item.classList.toggle('active', item === button);
        render();
      }});
    }}
    const money = value => value == null ? 'n/a' : '$' + Number(value || 0).toFixed(1);
    const integer = value => Number(value || 0).toLocaleString();
    const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, m => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}}[m]));
    function params() {{
      const p = new URLSearchParams();
      if (token) p.set('token', token);
      p.set('start', form.start.value);
      p.set('end', form.end.value);
      for (const input of form.querySelectorAll('input[name="role"]:checked')) p.append('role', input.value);
      return p;
    }}
    async function load() {{
      const response = await fetch('/admin/usage/data?' + params().toString(), {{ headers: {{ 'X-Dashboard-Token': token }} }});
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      state.data = data;
      render();
    }}
    function render() {{
      const data = state.data;
      if (!data) return;
      document.getElementById('periodLabel').textContent = data.start_time + ' to ' + data.end_time;
      document.getElementById('requests').textContent = integer(data.totals.request_count);
      document.getElementById('tokens').textContent = integer(data.totals.total_tokens);
      document.getElementById('estimated').textContent = money(data.totals.estimated_cost_usd);
      document.getElementById('actual').textContent = money(data.openai_org_actual_cost_usd);
      document.getElementById('cacheReads').textContent = integer(data.totals.cached_tokens);
      document.getElementById('cacheWrites').textContent = integer(data.totals.cache_write_tokens);
      document.getElementById('ordinaryInput').textContent = integer(data.totals.ordinary_input_tokens);
      document.getElementById('cacheSavings').textContent = money(data.totals.net_cache_savings_usd);
      userPivot(data);
      table('roles', data.role_totals, ['request_role','model','request_count','input_tokens','cached_tokens','cache_write_tokens','ordinary_input_tokens','cache_read_ratio','cache_write_ratio','net_cache_savings_usd','net_cache_savings_ratio', costKey()]);
      table('events', data.events, ['created_at','email','request_role','request_name','source_id','model','input_tokens','cached_tokens','cache_write_tokens','ordinary_input_tokens','net_cache_savings_usd', costKey(),'elapsed_ms']);
    }}
    function costKey() {{
      return state.costBasis === 'actual' ? 'actual_cost_usd' : 'estimated_cost_usd';
    }}
    function userPivot(data) {{
      const target = document.getElementById('users');
      const key = costKey();
      const models = Array.from(new Set((data.user_models || []).map(row => row.model))).sort();
      const rows = (data.users || []).map(user => {{
        const row = {{
          user_id: user.user_id,
          email: user.email || 'User ' + user.user_id,
          request_count: user.request_count || 0,
          total_tokens: user.total_tokens || 0,
          total: Number(user[key] || 0),
          models: Object.fromEntries(models.map(model => [model, 0]))
        }};
        for (const item of data.user_models || []) {{
          if (item.user_id === user.user_id && item.model) row.models[item.model] = Number(item[key] || 0);
        }}
        return row;
      }});
      rows.sort((a, b) => compare(sortValue(a, state.sort.key), sortValue(b, state.sort.key), state.sort.direction));
      const totals = {{
        request_count: rows.reduce((sum, row) => sum + row.request_count, 0),
        total_tokens: rows.reduce((sum, row) => sum + row.total_tokens, 0),
        total: rows.reduce((sum, row) => sum + row.total, 0),
        models: Object.fromEntries(models.map(model => [model, rows.reduce((sum, row) => sum + Number(row.models[model] || 0), 0)]))
      }};
      const columns = [
        {{ key: 'email', label: 'User', numeric: false }},
        {{ key: 'request_count', label: 'Requests', numeric: true }},
        {{ key: 'total_tokens', label: 'Tokens', numeric: true }},
        ...models.map(model => ({{ key: 'model:' + model, label: model, numeric: true }})),
        {{ key: 'total', label: 'Total', numeric: true }}
      ];
      target.innerHTML = '<table><thead><tr>' + columns.map(col => header(col)).join('') + '</tr></thead><tbody>' +
        rows.map(row => '<tr>' + columns.map(col => userCell(row, col)).join('') + '</tr>').join('') +
        '</tbody><tfoot><tr>' + columns.map(col => totalCell(totals, col)).join('') + '</tr></tfoot></table>';
      for (const th of target.querySelectorAll('th.sortable')) {{
        th.addEventListener('click', () => {{
          const key = th.dataset.sortKey;
          if (state.sort.key === key) state.sort.direction = state.sort.direction === 'asc' ? 'desc' : 'asc';
          else state.sort = {{ key, direction: 'desc' }};
          if (key === 'email') state.sort.direction = state.sort.direction === 'desc' ? 'asc' : state.sort.direction;
          render();
        }});
      }}
    }}
    function header(col) {{
      const sorted = state.sort.key === col.key ? ' sorted-' + state.sort.direction : '';
      return '<th class="' + (col.numeric ? 'num ' : '') + 'sortable' + sorted + '" data-sort-key="' + escapeHtml(col.key) + '">' + escapeHtml(col.label) + '</th>';
    }}
    function userCell(row, col) {{
      if (col.key === 'email') return '<td>' + escapeHtml(row.email) + '</td>';
      if (col.key === 'request_count') return '<td class="num">' + integer(row.request_count) + '</td>';
      if (col.key === 'total_tokens') return '<td class="num">' + integer(row.total_tokens) + '</td>';
      if (col.key.startsWith('model:')) return '<td class="num">' + money(row.models[col.key.slice(6)] || 0) + '</td>';
      return '<td class="num">' + money(row.total) + '</td>';
    }}
    function totalCell(totals, col) {{
      if (col.key === 'email') return '<td>Total</td>';
      if (col.key === 'request_count') return '<td class="num">' + integer(totals.request_count) + '</td>';
      if (col.key === 'total_tokens') return '<td class="num">' + integer(totals.total_tokens) + '</td>';
      if (col.key.startsWith('model:')) return '<td class="num">' + money(totals.models[col.key.slice(6)] || 0) + '</td>';
      return '<td class="num">' + money(totals.total) + '</td>';
    }}
    function sortValue(row, key) {{
      if (key.startsWith('model:')) return row.models[key.slice(6)] || 0;
      return row[key] ?? '';
    }}
    function compare(a, b, direction) {{
      const multiplier = direction === 'asc' ? 1 : -1;
      if (typeof a === 'string' || typeof b === 'string') return String(a).localeCompare(String(b)) * multiplier;
      return (Number(a || 0) - Number(b || 0)) * multiplier;
    }}
    function table(id, rows, cols) {{
      const target = document.getElementById(id);
      if (!rows.length) {{ target.innerHTML = '<div class="empty">No usage recorded for this period.</div>'; return; }}
      target.innerHTML = '<table><thead><tr>' + cols.map(c => '<th class="' + (numeric(c) ? 'num' : '') + '">' + label(c) + '</th>').join('') + '</tr></thead><tbody>' +
        rows.map(row => '<tr>' + cols.map(c => '<td class="' + (numeric(c) ? 'num' : '') + '">' + cell(row[c], c) + '</td>').join('') + '</tr>').join('') +
        '</tbody></table>';
    }}
    function numeric(c) {{ return c.includes('tokens') || c.includes('cost') || c.endsWith('_count') || c.endsWith('_ratio') || c === 'elapsed_ms'; }}
    function label(c) {{ return c.replaceAll('_', ' '); }}
    function cell(v, c) {{
      if (c.includes('cost')) return money(v);
      if (c.endsWith('_ratio')) return (Number(v || 0) * 100).toFixed(1) + '%';
      if (c.includes('tokens') || c.endsWith('_count') || c === 'elapsed_ms') return integer(v);
      return escapeHtml(v);
    }}
    load().catch(error => document.body.insertAdjacentHTML('beforeend', '<pre>' + error.message + '</pre>'));
  </script>
</body>
</html>"""


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

    if request.generated_lesson is not None:
        try:
            project_reference_dialogue(request.generated_lesson, expected_lesson_id=lesson_id)
        except SpeakingContextError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error

    for message in request.messages:
        if message.get("lesson_id") != lesson_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Message lesson_id must match path.",
            )
        if message.get("role") not in {"user", "assistant"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid message role.")


def _record_translation_lookup_if_present(
    *,
    database: Database,
    user_id: int,
    lookup: TranslationLookupRequest | None,
    source_kind: str,
    source_id: str,
) -> None:
    if lookup is None:
        return
    selected = lookup.selected_text.strip()
    if not selected or not source_id:
        return
    event = database.create_translation_lookup_event(
        user_id=user_id,
        source_kind=source_kind,
        source_id=source_id,
        source_surface=lookup.source_surface,
        selected_text=selected,
        normalized_text=" ".join(selected.casefold().split()),
        surrounding_text=lookup.surrounding_text,
        visible_course_level=lookup.visible_course_level,
        request_created_at=lookup.created_at,
    )
    snapshot = build_translation_lookup_evaluation_snapshot(
        database=database,
        catalog=get_learning_catalog(),
        user_id=user_id,
        lookup_event=event,
    )
    database.enqueue_translation_lookup_evaluation(
        user_id=user_id,
        lookup_event_id=int(event["id"]),
        snapshot=snapshot,
    )
