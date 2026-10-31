from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = Path("/home/dima/secure-secrets/llm.env")


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    gemini_api_key: str
    app_jwt_secret: str
    apple_client_id: str
    database_path: Path
    openai_admin_key: str | None = None
    elevenlabs_api_key: str | None = None
    anthropic_api_key: str | None = None
    usage_dashboard_token: str | None = None
    openai_usage_price_overrides: dict[str, dict[str, float]] | None = None
    openai_timeout_seconds: float = 240.0
    gemini_timeout_seconds: float = 300.0
    lesson_generator_model: str = "gpt-5.6-sol"
    lesson_generator_reasoning_effort: str = "medium"
    lesson_generator_recipe_version: str = "lesson_generator_v2"
    lesson_tts_model: str = "gemini-2.5-pro-preview-tts"
    lesson_tts_voice_config_version: str = "anna-aoede_erik-enceladus_v1"
    lesson_tts_recipe_version: str = "lesson_tts_v2"
    shared_audio_directory: Path | None = None
    shared_lesson_artifacts_enabled: bool = True
    evaluator_model: str = "gpt-5.6-sol"
    evaluator_reasoning_effort: str = "medium"
    vocabulary_quiz_model: str = "gpt-5.6-terra"
    vocabulary_quiz_reasoning_effort: str = "medium"
    vocabulary_interactor_model: str = "gpt-5.6-terra"
    vocabulary_interactor_reasoning_effort: str = "low"
    evaluation_worker_enabled: bool = False
    evaluation_worker_interval_seconds: float = 2.0
    lesson_audio_worker_enabled: bool = False
    lesson_audio_worker_interval_seconds: float = 1.0
    lesson_audio_max_attempts: int = 4
    lesson_audio_lease_seconds: int = 360
    lesson_audio_max_queued_per_user: int = 5
    lesson_audio_retry_cooldown_seconds: int = 10
    speaker_model: str = "claude-sonnet-5-5"
    speaker_reasoning_effort: str = "low"
    speaker_transcription_model: str = "gpt-transcribe"
    speaker_tts_model: str = "eleven_v4_turbo"
    speaker_tts_voice_id: str = "4Ct5uMEndw4cJ7q0Jx0l"
    speaker_provider_timeout_seconds: float = 30.0
    speaking_session_timeout_seconds: int = 600
    speaking_start_cooldown_seconds: int = 10
    speaking_start_window_seconds: int = 600
    speaking_max_starts_per_window: int = 6


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _required(values: dict[str, str], key: str) -> str:
    value = values.get(key) or os.environ.get(key)
    if not value:
        raise RuntimeError(f"Missing required backend setting: {key}")
    return value


def _optional(values: dict[str, str], key: str) -> str | None:
    return values.get(key) or os.environ.get(key)


def _json_object(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise RuntimeError("Expected JSON object for OPENAI_USAGE_PRICE_OVERRIDES_JSON")
    return decoded


def load_settings() -> Settings:
    env_path = Path(os.environ.get("SVENSKA_ENV_PATH", DEFAULT_ENV_PATH))
    values = _load_env_file(env_path)
    database_path = Path(
        values.get("SVENSKA_DATABASE_PATH")
        or os.environ.get("SVENSKA_DATABASE_PATH")
        or REPO_ROOT / "backend" / "data" / "svenska.db"
    )

    return Settings(
        openai_api_key=_required(values, "OPENAI_API_KEY"),
        gemini_api_key=_required(values, "GEMINI_API_KEY"),
        app_jwt_secret=_required(values, "APP_JWT_SECRET"),
        apple_client_id=_required(values, "APPLE_CLIENT_ID"),
        database_path=database_path,
        openai_admin_key=_optional(values, "OPENAI_ADMIN_KEY"),
        elevenlabs_api_key=_optional(values, "ELEVENLABS_API_KEY"),
        anthropic_api_key=_optional(values, "ANTHROPIC_API_KEY"),
        usage_dashboard_token=_optional(values, "SVENSKA_USAGE_DASHBOARD_TOKEN"),
        openai_usage_price_overrides=_json_object(_optional(values, "OPENAI_USAGE_PRICE_OVERRIDES_JSON")),
        lesson_generator_model=values.get("OPENAI_LESSON_GENERATOR_MODEL")
        or os.environ.get("OPENAI_LESSON_GENERATOR_MODEL")
        or "gpt-5.6-sol",
        lesson_generator_reasoning_effort=values.get("OPENAI_LESSON_GENERATOR_REASONING_EFFORT")
        or os.environ.get("OPENAI_LESSON_GENERATOR_REASONING_EFFORT")
        or "medium",
        lesson_generator_recipe_version=values.get("SVENSKA_LESSON_GENERATOR_RECIPE_VERSION")
        or os.environ.get("SVENSKA_LESSON_GENERATOR_RECIPE_VERSION")
        or "lesson_generator_v2",
        lesson_tts_model=values.get("GEMINI_LESSON_TTS_MODEL")
        or os.environ.get("GEMINI_LESSON_TTS_MODEL")
        or "gemini-2.5-pro-preview-tts",
        lesson_tts_voice_config_version=values.get("SVENSKA_LESSON_TTS_VOICE_CONFIG_VERSION")
        or os.environ.get("SVENSKA_LESSON_TTS_VOICE_CONFIG_VERSION")
        or "anna-aoede_erik-enceladus_v1",
        lesson_tts_recipe_version=values.get("SVENSKA_LESSON_TTS_RECIPE_VERSION")
        or os.environ.get("SVENSKA_LESSON_TTS_RECIPE_VERSION")
        or "lesson_tts_v2",
        shared_audio_directory=Path(
            values.get("SVENSKA_SHARED_AUDIO_DIRECTORY")
            or os.environ.get("SVENSKA_SHARED_AUDIO_DIRECTORY")
            or database_path.parent / "shared_lesson_audio"
        ),
        shared_lesson_artifacts_enabled=(
            values.get("SVENSKA_SHARED_LESSON_ARTIFACTS_ENABLED")
            or os.environ.get("SVENSKA_SHARED_LESSON_ARTIFACTS_ENABLED")
            or "1"
        ).lower()
        not in {"0", "false", "no"},
        evaluator_model=values.get("OPENAI_EVALUATOR_MODEL")
        or os.environ.get("OPENAI_EVALUATOR_MODEL")
        or "gpt-5.6-sol",
        evaluator_reasoning_effort=values.get("OPENAI_EVALUATOR_REASONING_EFFORT")
        or os.environ.get("OPENAI_EVALUATOR_REASONING_EFFORT")
        or "medium",
        vocabulary_quiz_model=values.get("OPENAI_VOCABULARY_QUIZ_MODEL")
        or os.environ.get("OPENAI_VOCABULARY_QUIZ_MODEL")
        or "gpt-5.6-terra",
        vocabulary_quiz_reasoning_effort=values.get("OPENAI_VOCABULARY_QUIZ_REASONING_EFFORT")
        or os.environ.get("OPENAI_VOCABULARY_QUIZ_REASONING_EFFORT")
        or "medium",
        vocabulary_interactor_model=values.get("OPENAI_VOCABULARY_INTERACTOR_MODEL")
        or os.environ.get("OPENAI_VOCABULARY_INTERACTOR_MODEL")
        or "gpt-5.6-terra",
        vocabulary_interactor_reasoning_effort=values.get("OPENAI_VOCABULARY_INTERACTOR_REASONING_EFFORT")
        or os.environ.get("OPENAI_VOCABULARY_INTERACTOR_REASONING_EFFORT")
        or "low",
        evaluation_worker_enabled=(
            values.get("SVENSKA_EVALUATION_WORKER_ENABLED")
            or os.environ.get("SVENSKA_EVALUATION_WORKER_ENABLED")
            or "1"
        ).lower()
        not in {"0", "false", "no"},
        lesson_audio_worker_enabled=(
            values.get("SVENSKA_LESSON_AUDIO_WORKER_ENABLED")
            or os.environ.get("SVENSKA_LESSON_AUDIO_WORKER_ENABLED")
            or "1"
        ).lower()
        not in {"0", "false", "no"},
        lesson_audio_worker_interval_seconds=float(
            values.get("SVENSKA_LESSON_AUDIO_WORKER_INTERVAL_SECONDS")
            or os.environ.get("SVENSKA_LESSON_AUDIO_WORKER_INTERVAL_SECONDS")
            or "1"
        ),
        lesson_audio_max_attempts=int(
            values.get("SVENSKA_LESSON_AUDIO_MAX_ATTEMPTS")
            or os.environ.get("SVENSKA_LESSON_AUDIO_MAX_ATTEMPTS")
            or "4"
        ),
        lesson_audio_lease_seconds=int(
            values.get("SVENSKA_LESSON_AUDIO_LEASE_SECONDS")
            or os.environ.get("SVENSKA_LESSON_AUDIO_LEASE_SECONDS")
            or "360"
        ),
        lesson_audio_max_queued_per_user=int(
            values.get("SVENSKA_LESSON_AUDIO_MAX_QUEUED_PER_USER")
            or os.environ.get("SVENSKA_LESSON_AUDIO_MAX_QUEUED_PER_USER")
            or "5"
        ),
        lesson_audio_retry_cooldown_seconds=int(
            values.get("SVENSKA_LESSON_AUDIO_RETRY_COOLDOWN_SECONDS")
            or os.environ.get("SVENSKA_LESSON_AUDIO_RETRY_COOLDOWN_SECONDS")
            or "10"
        ),
        speaker_model=values.get("SVENSKA_SPEAKER_MODEL")
        or os.environ.get("SVENSKA_SPEAKER_MODEL")
        or "claude-sonnet-5-5",
        speaker_reasoning_effort=values.get("SVENSKA_SPEAKER_REASONING_EFFORT")
        or os.environ.get("SVENSKA_SPEAKER_REASONING_EFFORT")
        or "low",
        speaker_transcription_model=values.get("SVENSKA_SPEAKER_TRANSCRIPTION_MODEL")
        or os.environ.get("SVENSKA_SPEAKER_TRANSCRIPTION_MODEL")
        or "gpt-transcribe",
        speaker_tts_model=values.get("SVENSKA_SPEAKER_TTS_MODEL")
        or os.environ.get("SVENSKA_SPEAKER_TTS_MODEL")
        or "eleven_v4_turbo",
        speaker_tts_voice_id=values.get("SVENSKA_SPEAKER_TTS_VOICE_ID")
        or os.environ.get("SVENSKA_SPEAKER_TTS_VOICE_ID")
        or "4Ct5uMEndw4cJ7q0Jx0l",
        speaker_provider_timeout_seconds=float(
            values.get("SVENSKA_SPEAKER_PROVIDER_TIMEOUT_SECONDS")
            or os.environ.get("SVENSKA_SPEAKER_PROVIDER_TIMEOUT_SECONDS")
            or "30"
        ),
        speaking_session_timeout_seconds=int(
            values.get("SVENSKA_SPEAKING_SESSION_TIMEOUT_SECONDS")
            or os.environ.get("SVENSKA_SPEAKING_SESSION_TIMEOUT_SECONDS")
            or "600"
        ),
        speaking_start_cooldown_seconds=int(
            values.get("SVENSKA_SPEAKING_START_COOLDOWN_SECONDS")
            or os.environ.get("SVENSKA_SPEAKING_START_COOLDOWN_SECONDS")
            or "10"
        ),
        speaking_start_window_seconds=int(
            values.get("SVENSKA_SPEAKING_START_WINDOW_SECONDS")
            or os.environ.get("SVENSKA_SPEAKING_START_WINDOW_SECONDS")
            or "600"
        ),
        speaking_max_starts_per_window=int(
            values.get("SVENSKA_SPEAKING_MAX_STARTS_PER_WINDOW")
            or os.environ.get("SVENSKA_SPEAKING_MAX_STARTS_PER_WINDOW")
            or "6"
        ),
    )
