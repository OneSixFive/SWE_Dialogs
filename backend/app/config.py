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
    usage_dashboard_token: str | None = None
    openai_usage_price_overrides: dict[str, dict[str, float]] | None = None
    openai_timeout_seconds: float = 240.0
    gemini_timeout_seconds: float = 300.0
    evaluator_model: str = "gpt-5.5"
    evaluator_reasoning_effort: str = "medium"
    vocabulary_quiz_model: str = "gpt-5.5"
    vocabulary_quiz_reasoning_effort: str = "medium"
    vocabulary_interactor_model: str = "gpt-5.5"
    vocabulary_interactor_reasoning_effort: str = "low"
    evaluation_worker_enabled: bool = False
    evaluation_worker_interval_seconds: float = 2.0


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
        usage_dashboard_token=_optional(values, "SVENSKA_USAGE_DASHBOARD_TOKEN"),
        openai_usage_price_overrides=_json_object(_optional(values, "OPENAI_USAGE_PRICE_OVERRIDES_JSON")),
        evaluator_model=values.get("OPENAI_EVALUATOR_MODEL")
        or os.environ.get("OPENAI_EVALUATOR_MODEL")
        or "gpt-5.5",
        evaluator_reasoning_effort=values.get("OPENAI_EVALUATOR_REASONING_EFFORT")
        or os.environ.get("OPENAI_EVALUATOR_REASONING_EFFORT")
        or "medium",
        vocabulary_quiz_model=values.get("OPENAI_VOCABULARY_QUIZ_MODEL")
        or os.environ.get("OPENAI_VOCABULARY_QUIZ_MODEL")
        or "gpt-5.5",
        vocabulary_quiz_reasoning_effort=values.get("OPENAI_VOCABULARY_QUIZ_REASONING_EFFORT")
        or os.environ.get("OPENAI_VOCABULARY_QUIZ_REASONING_EFFORT")
        or "medium",
        vocabulary_interactor_model=values.get("OPENAI_VOCABULARY_INTERACTOR_MODEL")
        or os.environ.get("OPENAI_VOCABULARY_INTERACTOR_MODEL")
        or "gpt-5.5",
        vocabulary_interactor_reasoning_effort=values.get("OPENAI_VOCABULARY_INTERACTOR_REASONING_EFFORT")
        or os.environ.get("OPENAI_VOCABULARY_INTERACTOR_REASONING_EFFORT")
        or "low",
        evaluation_worker_enabled=(
            values.get("SVENSKA_EVALUATION_WORKER_ENABLED")
            or os.environ.get("SVENSKA_EVALUATION_WORKER_ENABLED")
            or "1"
        ).lower()
        not in {"0", "false", "no"},
    )
