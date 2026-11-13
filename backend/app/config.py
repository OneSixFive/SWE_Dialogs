from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = Path("/home/dima/secure-secrets/llm.env")

# ElevenLabs voice bank, shared by Speaking and lesson dialog audio. Any voice works in either mode.
# Names are matched case-insensitively, with spaces and hyphens treated as underscores.
ELEVENLABS_VOICES = {
    "isterichka_f": "4xkUqaR9MYOJHoaC1Nak",
    "tomnaya_f": "4Ct5uMEndw4cJ7q0Jx0l",
    "casual_millenial_f": "HqmZnnvy6tCQd8EGWKRT",
    "pushy_but_pleasant_f": "1Iztu4UHnTb9SUjJcpS1",
    "babka_f": "kPdGSxhZAqy4bmPAf9iJ",
    "dushnila_m": "4r815lcewEwv1BQ1Jize",
    "skazochnik_m": "Pl7pcT0MQ5oC83oklshh",
    "skanska_m": "Z2ic84BAXoRvhU0mvJIa",
    "krivlyaka_m": "7UMEOkIJdI4hjmR2SWNq",
    "pacanchik_m": "ouhIFI5XkmBelRRcJe51",
}
# Old names still accepted from env files.
ELEVENLABS_VOICE_ALIASES = {
    "default": "isterichka_f",
    "default_speaker": "isterichka_f",
    "mumbly": "casual_millenial_f",
    "casual_millenial": "casual_millenial_f",
    "pushy_but_pleasant": "pushy_but_pleasant_f",
    "babka": "babka_f",
    "dushnila": "dushnila_m",
    "elin": "tomnaya_f",
}

# Which voice each role uses. Flip a voice by changing the name here, then commit, sync, restart.
# Env overrides: SVENSKA_SPEAKER_TTS_VOICE_ID, SVENSKA_LESSON_TTS_ANNA_VOICE, SVENSKA_LESSON_TTS_ERIK_VOICE
# (each takes a bank name or a raw voice ID). Dialog voices apply only when lesson_tts_model is "eleven_*".
SPEAKER_VOICE = "isterichka_f"
DIALOG_ANNA_VOICE = "babka_f"
DIALOG_ERIK_VOICE = "dushnila_m"
# True: each lesson's dialog gets Anna from the bank's "_f" voices and Erik from its "_m" voices, picked from a
# hash of the dialogue (same lesson, same voices). False: the fixed DIALOG_ANNA_VOICE / DIALOG_ERIK_VOICE.
# Env override: SVENSKA_LESSON_TTS_RANDOM_VOICES (1/0).
DIALOG_RANDOM_VOICES = True


def elevenlabs_voice_id(value: str) -> str:
    """Resolve a bank name (or old alias) to its voice ID; anything else is taken as a raw voice ID."""
    value = value.strip()
    key = value.lower().replace(" ", "_").replace("-", "_")
    key = ELEVENLABS_VOICE_ALIASES.get(key, key)
    return ELEVENLABS_VOICES.get(key, value)


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
    lesson_tts_model: str = "eleven_v4_turbo"
    lesson_tts_voice_config_version: str = "anna-aoede_erik-enceladus_v1"
    lesson_tts_recipe_version: str = "lesson_tts_v2"
    # ElevenLabs dialog voices, used when lesson_tts_model starts with "eleven".
    lesson_tts_anna_voice_id: str = elevenlabs_voice_id(DIALOG_ANNA_VOICE)
    lesson_tts_erik_voice_id: str = elevenlabs_voice_id(DIALOG_ERIK_VOICE)
    lesson_tts_random_voices: bool = DIALOG_RANDOM_VOICES
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
    # "split": per reply a checker and a conversationalist run in parallel on the stored per-lesson plan;
    # "planned": one Speaker call on that plan; "classic": the original Speaker prompt without a plan.
    speaker_mode: str = "split"
    speaker_misheard_retry_mode: str = "off"
    speaking_plan_model: str = "claude-opus-5-5"
    speaking_plan_reasoning_effort: str = "medium"
    speaker_model: str = "claude-sonnet-5-5"
    speaker_reasoning_effort: str = "medium"
    # Split mode's two calls; the provider follows the model name ("claude-*" is Anthropic, anything else OpenAI).
    speaker_conversation_model: str = "gpt-6.1-sol"
    speaker_conversation_reasoning_effort: str = "low"
    speaker_check_model: str = "gpt-6.1-sol"
    speaker_check_reasoning_effort: str = "low"
    # The Replier: suggests a learner reply on request (the hint key); same model as the conversationalist.
    speaker_replier_model: str = "gpt-6.1-sol"
    speaker_replier_reasoning_effort: str = "low"
    # "scribe_v3" (ElevenLabs) or "gpt-transcribe" (OpenAI); the provider follows the name.
    speaker_transcription_model: str = "scribe_v3"
    speaker_tts_model: str = "eleven_v4_turbo"
    speaker_tts_voice_id: str = elevenlabs_voice_id(SPEAKER_VOICE)
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


def _speaker_misheard_retry_mode(values: dict[str, str]) -> str:
    mode = _optional(values, "SVENSKA_SPEAKER_MISHEARD_RETRY_MODE")
    if mode is None:
        legacy = _optional(values, "SVENSKA_SPEAKER_MISHEARD_RETRY_ENABLED") or ""
        return "on" if legacy.strip().lower() in {"1", "true", "yes", "on"} else "off"
    mode = "_".join(mode.lower().split())
    if mode not in {"off", "on", "on_when_last"}:
        raise RuntimeError("SVENSKA_SPEAKER_MISHEARD_RETRY_MODE must be OFF, ON, or ON WHEN LAST")
    return mode


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
        lesson_tts_model=values.get("SVENSKA_LESSON_TTS_MODEL")
        or os.environ.get("SVENSKA_LESSON_TTS_MODEL")
        or values.get("GEMINI_LESSON_TTS_MODEL")
        or os.environ.get("GEMINI_LESSON_TTS_MODEL")
        or "eleven_v4_turbo",
        lesson_tts_voice_config_version=values.get("SVENSKA_LESSON_TTS_VOICE_CONFIG_VERSION")
        or os.environ.get("SVENSKA_LESSON_TTS_VOICE_CONFIG_VERSION")
        or "anna-aoede_erik-enceladus_v1",
        lesson_tts_recipe_version=values.get("SVENSKA_LESSON_TTS_RECIPE_VERSION")
        or os.environ.get("SVENSKA_LESSON_TTS_RECIPE_VERSION")
        or "lesson_tts_v2",
        lesson_tts_anna_voice_id=elevenlabs_voice_id(
            values.get("SVENSKA_LESSON_TTS_ANNA_VOICE")
            or os.environ.get("SVENSKA_LESSON_TTS_ANNA_VOICE")
            or DIALOG_ANNA_VOICE
        ),
        lesson_tts_erik_voice_id=elevenlabs_voice_id(
            values.get("SVENSKA_LESSON_TTS_ERIK_VOICE")
            or os.environ.get("SVENSKA_LESSON_TTS_ERIK_VOICE")
            or DIALOG_ERIK_VOICE
        ),
        lesson_tts_random_voices=(
            values.get("SVENSKA_LESSON_TTS_RANDOM_VOICES")
            or os.environ.get("SVENSKA_LESSON_TTS_RANDOM_VOICES")
            or ("1" if DIALOG_RANDOM_VOICES else "0")
        ).lower()
        not in {"0", "false", "no"},
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
        speaker_mode=values.get("SVENSKA_SPEAKER_MODE")
        or os.environ.get("SVENSKA_SPEAKER_MODE")
        or "split",
        speaker_misheard_retry_mode=_speaker_misheard_retry_mode(values),
        speaking_plan_model=values.get("SVENSKA_SPEAKING_PLAN_MODEL")
        or os.environ.get("SVENSKA_SPEAKING_PLAN_MODEL")
        or "claude-opus-5-5",
        speaking_plan_reasoning_effort=values.get("SVENSKA_SPEAKING_PLAN_REASONING_EFFORT")
        or os.environ.get("SVENSKA_SPEAKING_PLAN_REASONING_EFFORT")
        or "medium",
        speaker_model=values.get("SVENSKA_SPEAKER_MODEL")
        or os.environ.get("SVENSKA_SPEAKER_MODEL")
        or "claude-sonnet-5-5",
        speaker_reasoning_effort=values.get("SVENSKA_SPEAKER_REASONING_EFFORT")
        or os.environ.get("SVENSKA_SPEAKER_REASONING_EFFORT")
        or "medium",
        speaker_conversation_model=values.get("SVENSKA_SPEAKER_CONVERSATION_MODEL")
        or os.environ.get("SVENSKA_SPEAKER_CONVERSATION_MODEL")
        or "gpt-6.1-sol",
        speaker_conversation_reasoning_effort=values.get("SVENSKA_SPEAKER_CONVERSATION_REASONING_EFFORT")
        or os.environ.get("SVENSKA_SPEAKER_CONVERSATION_REASONING_EFFORT")
        or "low",
        speaker_check_model=values.get("SVENSKA_SPEAKER_CHECK_MODEL")
        or os.environ.get("SVENSKA_SPEAKER_CHECK_MODEL")
        or "gpt-6.1-sol",
        speaker_check_reasoning_effort=values.get("SVENSKA_SPEAKER_CHECK_REASONING_EFFORT")
        or os.environ.get("SVENSKA_SPEAKER_CHECK_REASONING_EFFORT")
        or "low",
        speaker_replier_model=values.get("SVENSKA_SPEAKER_REPLIER_MODEL")
        or os.environ.get("SVENSKA_SPEAKER_REPLIER_MODEL")
        or "gpt-6.1-sol",
        speaker_replier_reasoning_effort=values.get("SVENSKA_SPEAKER_REPLIER_REASONING_EFFORT")
        or os.environ.get("SVENSKA_SPEAKER_REPLIER_REASONING_EFFORT")
        or "low",
        speaker_transcription_model=values.get("SVENSKA_SPEAKER_TRANSCRIPTION_MODEL")
        or os.environ.get("SVENSKA_SPEAKER_TRANSCRIPTION_MODEL")
        or "scribe_v3",
        speaker_tts_model=values.get("SVENSKA_SPEAKER_TTS_MODEL")
        or os.environ.get("SVENSKA_SPEAKER_TTS_MODEL")
        or "eleven_v4_turbo",
        speaker_tts_voice_id=elevenlabs_voice_id(
            values.get("SVENSKA_SPEAKER_TTS_VOICE_ID")
            or os.environ.get("SVENSKA_SPEAKER_TTS_VOICE_ID")
            or SPEAKER_VOICE
        ),
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
