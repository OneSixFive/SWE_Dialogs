from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Response, status

from .auth import get_database, get_settings, issue_session_token, require_user, verify_apple_identity_token
from .config import Settings
from .db import Database
from .gemini_client import generate_wav
from .models import AppleAuthRequest, AppleAuthResponse, LessonGenerateRequest, LessonMessageRequest, TTSRequest, UserSummary
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
        user=UserSummary(id=user.id, apple_sub=user.apple_sub, email=user.email),
    )


@app.post("/lessons/generate")
async def lessons_generate(
    request: LessonGenerateRequest,
    _: str = Depends(require_user),
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
    _: str = Depends(require_user),
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
    _: str = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> Response:
    wav_data = await generate_wav(settings, dialog=request.dialog, model=request.model)
    return Response(content=wav_data, media_type="audio/wav")
