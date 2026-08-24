from __future__ import annotations

import json
import hashlib
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .lesson_audio import DEFAULT_TTS_MODEL, VOICE_CONFIG_VERSION, lesson_audio_content_hash


logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class User:
    id: int
    apple_sub: str
    email: str | None


@dataclass(frozen=True)
class LessonSession:
    lesson_id: str
    state: dict[str, Any]
    generated_lesson: dict[str, Any] | None
    messages: list[dict[str, Any]]
    chat_summary: dict[str, Any] | None
    status: str
    is_completed: bool
    completed_at: str | None
    client_updated_at: str
    server_updated_at: str
    state_schema_version: int
    content_schema_version: int
    has_audio: bool
    lesson_artifact_id: str | None = None


@dataclass(frozen=True)
class LessonAudio:
    lesson_id: str
    audio_data: bytes
    content_type: str
    byte_count: int
    generated_at: str
    updated_at: str
    content_hash: str
    job_id: int | None
    model: str
    voice_config_version: str


@dataclass(frozen=True)
class LessonAudioJob:
    id: int
    user_id: int
    lesson_id: str
    content_hash: str
    status: str
    attempt_count: int
    next_attempt_at: str
    lease_expires_at: str | None
    provider: str
    model: str
    voice_config_version: str
    last_error_code: str | None
    last_error_summary: str | None
    created_at: str
    updated_at: str
    completed_at: str | None


@dataclass(frozen=True)
class LessonArtifact:
    id: str
    lesson_id: str
    scope: str
    owner_user_id: int | None
    recipe_fingerprint: str
    recipe: dict[str, Any]
    lesson_content_hash: str
    generated_lesson: dict[str, Any]
    requested_model: str
    provider_model: str | None
    reasoning_effort: str
    provider_request_id: str | None
    created_by_user_id: int
    created_at: str
    invalidated_at: str | None


@dataclass(frozen=True)
class LessonGenerationJob:
    id: int
    lesson_id: str
    recipe_fingerprint: str
    recipe: dict[str, Any]
    scope: str
    owner_user_id: int | None
    requested_by_user_id: int
    status: str
    attempt_count: int
    lease_expires_at: str | None
    artifact_id: str | None
    last_error_code: str | None
    updated_at: str


@dataclass(frozen=True)
class ArtifactAudio:
    lesson_artifact_id: str
    content_hash: str
    audio_recipe_fingerprint: str
    relative_file_path: str
    content_type: str
    byte_count: int
    model: str
    voice_config_version: str
    updated_at: str


@dataclass(frozen=True)
class ArtifactAudioJob:
    id: int
    lesson_artifact_id: str
    requested_by_user_id: int
    lesson_id: str
    content_hash: str
    dialogue_text_hash: str
    audio_recipe_fingerprint: str
    status: str
    attempt_count: int
    next_attempt_at: str
    lease_expires_at: str | None
    model: str
    voice_config_version: str
    last_error_code: str | None
    updated_at: str


class LessonSessionConflict(Exception):
    def __init__(self, current: LessonSession) -> None:
        super().__init__("Lesson session conflict.")
        self.current = current


@dataclass(frozen=True)
class EvaluationJob:
    id: int
    user_id: int
    source_kind: str
    source_id: str
    input_snapshot: dict[str, Any]
    attempt_count: int
    prompt_version: str


@dataclass(frozen=True)
class VocabularyPracticeSession:
    id: str
    course_level: str
    stage_number: int
    progress_cutoff_absolute_day: int
    status: str
    selection_snapshot: dict[str, Any]
    quiz: dict[str, Any] | None
    state: dict[str, Any]
    messages: list[dict[str, Any]]
    created_at: str
    updated_at: str
    completed_at: str | None


@dataclass(frozen=True)
class UsageDashboardSummary:
    start_time: str
    end_time: str
    roles: list[str]
    totals: dict[str, Any]
    users: list[dict[str, Any]]
    user_models: list[dict[str, Any]]
    role_totals: list[dict[str, Any]]
    events: list[dict[str, Any]]


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _init(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            self._apply_migration(
                connection,
                1,
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    apple_sub TEXT NOT NULL UNIQUE,
                    email TEXT,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                )
                """,
            )
            self._apply_migration(
                connection,
                2,
                """
                CREATE TABLE IF NOT EXISTS lesson_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    lesson_id TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    generated_lesson_json TEXT NULL,
                    messages_json TEXT NOT NULL DEFAULT '[]',
                    chat_summary_json TEXT NULL,
                    state_schema_version INTEGER NOT NULL DEFAULT 1,
                    content_schema_version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL CHECK (
                        status IN (
                            'not_started',
                            'generated',
                            'listening',
                            'comprehension',
                            'discussion',
                            'translation',
                            'completed'
                        )
                    ),
                    is_completed INTEGER NOT NULL DEFAULT 0,
                    completed_at TEXT NULL,
                    client_updated_at TEXT NOT NULL,
                    server_updated_at TEXT NOT NULL,
                    deleted_at TEXT NULL,
                    UNIQUE(user_id, lesson_id)
                );

                CREATE INDEX IF NOT EXISTS idx_lesson_sessions_user_updated
                    ON lesson_sessions(user_id, server_updated_at);
                CREATE INDEX IF NOT EXISTS idx_lesson_sessions_user_lesson
                    ON lesson_sessions(user_id, lesson_id);
                CREATE INDEX IF NOT EXISTS idx_lesson_sessions_user_completed
                    ON lesson_sessions(user_id, is_completed);
                """,
            )
            self._apply_migration(
                connection,
                3,
                """
                CREATE TABLE IF NOT EXISTS lesson_progress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    lesson_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    is_completed INTEGER NOT NULL DEFAULT 0,
                    completed_at TEXT NULL,
                    score REAL NULL,
                    client_updated_at TEXT NOT NULL,
                    server_updated_at TEXT NOT NULL,
                    UNIQUE(user_id, lesson_id)
                );

                CREATE INDEX IF NOT EXISTS idx_lesson_progress_user_updated
                    ON lesson_progress(user_id, server_updated_at);

                CREATE TABLE IF NOT EXISTS vocabulary_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    lemma TEXT NOT NULL,
                    surface_form TEXT NULL,
                    part_of_speech TEXT NULL,
                    sense_key TEXT NULL,
                    translation TEXT NULL,
                    source_lesson_id TEXT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    mastery_score REAL NOT NULL DEFAULT 0,
                    evidence_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_vocabulary_items_user_normalized_key
                    ON vocabulary_items(
                        user_id,
                        lower(trim(lemma)),
                        COALESCE(part_of_speech, ''),
                        COALESCE(sense_key, '')
                    );
                CREATE INDEX IF NOT EXISTS idx_vocabulary_items_user_last_seen
                    ON vocabulary_items(user_id, last_seen_at);
                CREATE INDEX IF NOT EXISTS idx_vocabulary_items_user_mastery
                    ON vocabulary_items(user_id, mastery_score);

                CREATE TABLE IF NOT EXISTS vocabulary_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    vocabulary_item_id INTEGER NULL REFERENCES vocabulary_items(id) ON DELETE SET NULL,
                    lesson_id TEXT NULL,
                    event_type TEXT NOT NULL,
                    event_json TEXT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_vocabulary_events_user_created
                    ON vocabulary_events(user_id, created_at);

                CREATE TABLE IF NOT EXISTS grammar_skills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    description TEXT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS grammar_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    grammar_skill_id INTEGER NULL REFERENCES grammar_skills(id) ON DELETE SET NULL,
                    lesson_id TEXT NULL,
                    event_type TEXT NOT NULL,
                    event_json TEXT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_grammar_events_user_created
                    ON grammar_events(user_id, created_at);

                CREATE TABLE IF NOT EXISTS user_grammar_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    grammar_skill_id INTEGER NOT NULL REFERENCES grammar_skills(id) ON DELETE CASCADE,
                    strength_score REAL NOT NULL DEFAULT 0,
                    evidence_count INTEGER NOT NULL DEFAULT 0,
                    last_updated_at TEXT NOT NULL,
                    UNIQUE(user_id, grammar_skill_id)
                );
                CREATE INDEX IF NOT EXISTS idx_user_grammar_stats_user_strength
                    ON user_grammar_stats(user_id, strength_score);
                """,
            )
            self._apply_migration(
                connection,
                4,
                """
                CREATE TABLE IF NOT EXISTS dialog_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    lesson_id TEXT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NULL,
                    summary_json TEXT NULL,
                    retention_policy TEXT NOT NULL DEFAULT 'summary_only'
                );
                CREATE INDEX IF NOT EXISTS idx_dialog_sessions_user_started
                    ON dialog_sessions(user_id, started_at);

                CREATE TABLE IF NOT EXISTS dialog_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES dialog_sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """,
            )
            self._apply_migration(
                connection,
                5,
                """
                CREATE TABLE IF NOT EXISTS user_learning_targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    target_kind TEXT NOT NULL CHECK (target_kind IN ('vocabulary', 'grammar')),
                    target_key TEXT NOT NULL,
                    display_text TEXT NOT NULL,
                    target_subtype TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('active', 'resolved')),
                    priority_score REAL NOT NULL DEFAULT 0,
                    success_streak INTEGER NOT NULL DEFAULT 0,
                    struggle_count INTEGER NOT NULL DEFAULT 0,
                    evidence_count INTEGER NOT NULL DEFAULT 0,
                    source_level TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_evaluated_at TEXT NOT NULL,
                    resolved_at TEXT NULL,
                    UNIQUE(user_id, target_kind, target_key)
                );
                CREATE INDEX IF NOT EXISTS idx_user_learning_targets_retrieval
                    ON user_learning_targets(user_id, status, priority_score DESC, last_evaluated_at ASC);

                CREATE TABLE IF NOT EXISTS evaluation_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    source_kind TEXT NOT NULL CHECK (source_kind IN ('lesson', 'vocabulary_practice')),
                    source_id TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    input_snapshot_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('pending', 'running', 'succeeded', 'skipped_no_evidence', 'failed')
                    ),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NULL,
                    lease_expires_at TEXT NULL,
                    prompt_version TEXT NOT NULL,
                    model TEXT NULL,
                    raw_output_json TEXT NULL,
                    last_error TEXT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT NULL,
                    UNIQUE(user_id, source_kind, source_id, input_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_evaluation_jobs_claim
                    ON evaluation_jobs(status, next_attempt_at, lease_expires_at, created_at);

                CREATE TABLE IF NOT EXISTS learning_evidence_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    learning_target_id INTEGER NOT NULL REFERENCES user_learning_targets(id) ON DELETE CASCADE,
                    evaluation_job_id INTEGER NOT NULL REFERENCES evaluation_jobs(id) ON DELETE CASCADE,
                    source_kind TEXT NOT NULL CHECK (source_kind IN ('lesson', 'vocabulary_practice')),
                    source_id TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK (outcome IN ('struggled', 'partial', 'demonstrated')),
                    evidence_strength TEXT NOT NULL CHECK (
                        evidence_strength IN ('production', 'recognition', 'assisted_production')
                    ),
                    confidence REAL NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(evaluation_job_id, learning_target_id)
                );
                CREATE INDEX IF NOT EXISTS idx_learning_evidence_target_created
                    ON learning_evidence_events(learning_target_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS vocabulary_practice_sessions (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    course_level TEXT NOT NULL,
                    stage_number INTEGER NOT NULL,
                    progress_cutoff_absolute_day INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('generating', 'active', 'completed', 'abandoned', 'failed')
                    ),
                    selection_snapshot_json TEXT NOT NULL,
                    quiz_json TEXT NULL,
                    state_json TEXT NOT NULL,
                    messages_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_vocabulary_practices_user_created
                    ON vocabulary_practice_sessions(user_id, created_at DESC);
                """,
            )
            self._apply_migration(
                connection,
                6,
                """
                PRAGMA foreign_keys = OFF;

                CREATE TABLE IF NOT EXISTS translation_lookup_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    source_kind TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_surface TEXT NULL,
                    selected_text TEXT NOT NULL,
                    normalized_text TEXT NOT NULL,
                    surrounding_text TEXT NULL,
                    visible_course_level TEXT NULL,
                    request_created_at TEXT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'evaluated', 'ignored', 'failed')),
                    created_at TEXT NOT NULL,
                    evaluated_at TEXT NULL,
                    last_error TEXT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_translation_lookup_events_user_created
                    ON translation_lookup_events(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_translation_lookup_events_status
                    ON translation_lookup_events(status, created_at);

                ALTER TABLE learning_evidence_events RENAME TO learning_evidence_events_old;
                ALTER TABLE evaluation_jobs RENAME TO evaluation_jobs_old;

                CREATE TABLE evaluation_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    source_kind TEXT NOT NULL CHECK (source_kind IN ('lesson', 'vocabulary_practice', 'translation_lookup')),
                    source_id TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    input_snapshot_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('pending', 'running', 'succeeded', 'skipped_no_evidence', 'failed')
                    ),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NULL,
                    lease_expires_at TEXT NULL,
                    prompt_version TEXT NOT NULL,
                    model TEXT NULL,
                    raw_output_json TEXT NULL,
                    last_error TEXT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT NULL,
                    UNIQUE(user_id, source_kind, source_id, input_hash)
                );
                INSERT INTO evaluation_jobs (
                    id, user_id, source_kind, source_id, input_hash, input_snapshot_json,
                    status, attempt_count, next_attempt_at, lease_expires_at, prompt_version,
                    model, raw_output_json, last_error, created_at, completed_at
                )
                SELECT
                    id, user_id, source_kind, source_id, input_hash, input_snapshot_json,
                    status, attempt_count, next_attempt_at, lease_expires_at, prompt_version,
                    model, raw_output_json, last_error, created_at, completed_at
                FROM evaluation_jobs_old;
                CREATE TABLE learning_evidence_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    learning_target_id INTEGER NOT NULL REFERENCES user_learning_targets(id) ON DELETE CASCADE,
                    evaluation_job_id INTEGER NOT NULL REFERENCES evaluation_jobs(id) ON DELETE CASCADE,
                    source_kind TEXT NOT NULL CHECK (source_kind IN ('lesson', 'vocabulary_practice', 'translation_lookup')),
                    source_id TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK (outcome IN ('struggled', 'partial', 'demonstrated', 'lookup_requested')),
                    evidence_strength TEXT NOT NULL CHECK (
                        evidence_strength IN ('production', 'recognition', 'assisted_production', 'lookup')
                    ),
                    confidence REAL NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(evaluation_job_id, learning_target_id)
                );
                INSERT INTO learning_evidence_events (
                    id, user_id, learning_target_id, evaluation_job_id, source_kind, source_id,
                    outcome, evidence_strength, confidence, evidence_json, created_at
                )
                SELECT
                    id, user_id, learning_target_id, evaluation_job_id, source_kind, source_id,
                    outcome, evidence_strength, confidence, evidence_json, created_at
                FROM learning_evidence_events_old;
                DROP TABLE learning_evidence_events_old;
                DROP TABLE evaluation_jobs_old;
                CREATE INDEX IF NOT EXISTS idx_evaluation_jobs_claim
                    ON evaluation_jobs(status, next_attempt_at, lease_expires_at, created_at);
                CREATE INDEX IF NOT EXISTS idx_learning_evidence_target_created
                    ON learning_evidence_events(learning_target_id, created_at DESC);
                PRAGMA foreign_keys = ON;
                """,
            )
            self._apply_migration(
                connection,
                7,
                """
                CREATE TABLE IF NOT EXISTS openai_usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    request_role TEXT NOT NULL,
                    request_name TEXT NOT NULL,
                    source_id TEXT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT NULL,
                    prompt_cache_key TEXT NULL,
                    input_tokens INTEGER NULL,
                    cached_tokens INTEGER NULL,
                    output_tokens INTEGER NULL,
                    reasoning_tokens INTEGER NULL,
                    total_tokens INTEGER NULL,
                    estimated_cost_usd REAL NULL,
                    actual_cost_usd REAL NULL,
                    elapsed_ms INTEGER NOT NULL,
                    openai_request_id TEXT NULL,
                    created_at TEXT NOT NULL,
                    raw_usage_json TEXT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_openai_usage_created
                    ON openai_usage_events(created_at);
                CREATE INDEX IF NOT EXISTS idx_openai_usage_user_created
                    ON openai_usage_events(user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_openai_usage_role_created
                    ON openai_usage_events(request_role, created_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_openai_usage_request_id
                    ON openai_usage_events(openai_request_id)
                    WHERE openai_request_id IS NOT NULL;
                """,
            )
            self._apply_migration(
                connection,
                8,
                """
                CREATE TABLE IF NOT EXISTS lesson_audio_cache (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    lesson_id TEXT NOT NULL,
                    audio_data BLOB NOT NULL,
                    content_type TEXT NOT NULL DEFAULT 'audio/wav',
                    byte_count INTEGER NOT NULL,
                    completed_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, lesson_id)
                );
                CREATE INDEX IF NOT EXISTS idx_lesson_audio_cache_user_completed
                    ON lesson_audio_cache(user_id, completed_at DESC, updated_at DESC);
                """,
            )
            self._apply_migration(
                connection,
                9,
                """
                ALTER TABLE lesson_audio_cache RENAME COLUMN completed_at TO generated_at;
                DROP INDEX IF EXISTS idx_lesson_audio_cache_user_completed;
                CREATE INDEX IF NOT EXISTS idx_lesson_audio_cache_user_generated
                    ON lesson_audio_cache(user_id, generated_at DESC, updated_at DESC);
                """,
            )
            self._apply_migration(
                connection,
                10,
                """
                ALTER TABLE openai_usage_events ADD COLUMN cache_write_tokens INTEGER NULL;
                ALTER TABLE openai_usage_events ADD COLUMN ordinary_input_tokens INTEGER NULL;
                ALTER TABLE openai_usage_events ADD COLUMN effective_input_cost_usd REAL NULL;
                ALTER TABLE openai_usage_events ADD COLUMN uncached_input_cost_usd REAL NULL;
                ALTER TABLE openai_usage_events ADD COLUMN net_cache_savings_usd REAL NULL;
                UPDATE openai_usage_events
                SET cache_write_tokens = 0,
                    ordinary_input_tokens = MAX(
                        COALESCE(input_tokens, 0) - COALESCE(cached_tokens, 0),
                        0
                    );
                """,
            )
            self._apply_lesson_audio_migration(connection)
            self._backfill_lesson_audio_metadata(connection)
            self._apply_lesson_artifact_migration(connection)
            self._apply_migration(
                connection,
                13,
                """
                ALTER TABLE openai_usage_events ADD COLUMN provider_response_id TEXT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_openai_usage_provider_response_id
                    ON openai_usage_events(provider_response_id)
                    WHERE provider_response_id IS NOT NULL;
                """,
            )
            connection.execute(
                """
                UPDATE vocabulary_practice_sessions
                SET status = 'failed', updated_at = ?
                WHERE status = 'generating'
                """,
                (_now_iso(),),
            )
            connection.commit()

    def _apply_lesson_artifact_migration(self, connection: sqlite3.Connection) -> None:
        row = connection.execute("SELECT 1 FROM schema_migrations WHERE version = 12").fetchone()
        if row is not None:
            return
        existing_session_columns = {
            str(column["name"])
            for column in connection.execute("PRAGMA table_info(lesson_sessions)").fetchall()
        }
        if "lesson_artifact_id" not in existing_session_columns:
            connection.execute("ALTER TABLE lesson_sessions ADD COLUMN lesson_artifact_id TEXT NULL")
        connection.executescript(
            """
            CREATE TABLE lesson_artifacts (
                id TEXT PRIMARY KEY,
                lesson_id TEXT NOT NULL,
                scope TEXT NOT NULL CHECK (scope IN ('shared', 'private')),
                owner_user_id INTEGER NULL REFERENCES users(id) ON DELETE CASCADE,
                recipe_fingerprint TEXT NOT NULL,
                recipe_json TEXT NOT NULL,
                lesson_content_hash TEXT NOT NULL,
                generated_lesson_json TEXT NOT NULL,
                requested_model TEXT NOT NULL,
                provider_model TEXT NULL,
                reasoning_effort TEXT NOT NULL,
                provider_request_id TEXT NULL,
                created_by_user_id INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,
                invalidated_at TEXT NULL,
                invalidation_reason TEXT NULL,
                CHECK ((scope = 'shared' AND owner_user_id IS NULL)
                    OR (scope = 'private' AND owner_user_id IS NOT NULL))
            );
            CREATE UNIQUE INDEX idx_lesson_artifacts_shared_recipe
                ON lesson_artifacts(lesson_id, recipe_fingerprint)
                WHERE scope = 'shared' AND invalidated_at IS NULL;
            CREATE INDEX idx_lesson_artifacts_owner_lesson
                ON lesson_artifacts(owner_user_id, lesson_id, created_at);

            CREATE TABLE lesson_generation_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lesson_id TEXT NOT NULL,
                recipe_fingerprint TEXT NOT NULL,
                recipe_json TEXT NOT NULL,
                scope TEXT NOT NULL CHECK (scope IN ('shared', 'private')),
                owner_user_id INTEGER NULL REFERENCES users(id) ON DELETE CASCADE,
                requested_by_user_id INTEGER NOT NULL REFERENCES users(id),
                status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'superseded')),
                attempt_count INTEGER NOT NULL DEFAULT 0,
                lease_expires_at TEXT NULL,
                artifact_id TEXT NULL REFERENCES lesson_artifacts(id),
                last_error_code TEXT NULL,
                last_error_summary TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT NULL
            );
            CREATE UNIQUE INDEX idx_lesson_generation_jobs_shared_recipe
                ON lesson_generation_jobs(lesson_id, recipe_fingerprint)
                WHERE scope = 'shared';
            CREATE INDEX idx_lesson_generation_jobs_owner
                ON lesson_generation_jobs(owner_user_id, updated_at);

            CREATE TABLE artifact_audio_cache (
                lesson_artifact_id TEXT NOT NULL REFERENCES lesson_artifacts(id) ON DELETE CASCADE,
                audio_recipe_fingerprint TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                dialogue_text_hash TEXT NOT NULL,
                relative_file_path TEXT NOT NULL,
                content_type TEXT NOT NULL DEFAULT 'audio/wav',
                byte_count INTEGER NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                voice_config_version TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (lesson_artifact_id, audio_recipe_fingerprint)
            );
            CREATE INDEX idx_artifact_audio_cache_hash ON artifact_audio_cache(content_hash);

            CREATE TABLE artifact_audio_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lesson_artifact_id TEXT NOT NULL REFERENCES lesson_artifacts(id) ON DELETE CASCADE,
                requested_by_user_id INTEGER NOT NULL REFERENCES users(id),
                lesson_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                dialogue_text_hash TEXT NOT NULL,
                audio_recipe_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'superseded')),
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                lease_expires_at TEXT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                voice_config_version TEXT NOT NULL,
                last_error_code TEXT NULL,
                last_error_summary TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT NULL,
                UNIQUE (lesson_artifact_id, audio_recipe_fingerprint)
            );
            CREATE INDEX idx_artifact_audio_jobs_claim
                ON artifact_audio_jobs(status, next_attempt_at, lease_expires_at, created_at);
            """
        )
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (12, ?)",
            (_now_iso(),),
        )

    def _apply_lesson_audio_migration(self, connection: sqlite3.Connection) -> None:
        row = connection.execute("SELECT 1 FROM schema_migrations WHERE version = 11").fetchone()
        if row is not None:
            return
        connection.execute(
            """
                CREATE TABLE IF NOT EXISTS lesson_audio_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    lesson_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'superseded')),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    lease_expires_at TEXT NULL,
                    provider TEXT NOT NULL DEFAULT 'gemini',
                    model TEXT NOT NULL,
                    voice_config_version TEXT NOT NULL,
                    last_error_code TEXT NULL,
                    last_error_summary TEXT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT NULL,
                    UNIQUE(user_id, lesson_id, content_hash)
                )
            """
        )
        existing_columns = {
            str(column["name"])
            for column in connection.execute("PRAGMA table_info(lesson_audio_cache)").fetchall()
        }
        additions = {
            "content_hash": "TEXT NULL",
            "job_id": "INTEGER NULL REFERENCES lesson_audio_jobs(id)",
            "model": "TEXT NULL",
            "voice_config_version": "TEXT NULL",
        }
        for name, declaration in additions.items():
            if name not in existing_columns:
                connection.execute(f"ALTER TABLE lesson_audio_cache ADD COLUMN {name} {declaration}")
        connection.executescript(
            """
                CREATE INDEX IF NOT EXISTS idx_lesson_audio_jobs_claim
                    ON lesson_audio_jobs(status, next_attempt_at, lease_expires_at, created_at);
                CREATE INDEX IF NOT EXISTS idx_lesson_audio_jobs_user_lesson
                    ON lesson_audio_jobs(user_id, lesson_id, updated_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_lesson_audio_cache_identity
                    ON lesson_audio_cache(user_id, lesson_id, content_hash)
                    WHERE content_hash IS NOT NULL;
            """
        )
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (11, ?)",
            (_now_iso(),),
        )

    def _backfill_lesson_audio_metadata(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT cache.user_id, cache.lesson_id, sessions.generated_lesson_json
            FROM lesson_audio_cache AS cache
            JOIN lesson_sessions AS sessions
              ON sessions.user_id = cache.user_id AND sessions.lesson_id = cache.lesson_id
            WHERE cache.content_hash IS NULL
              AND sessions.deleted_at IS NULL
              AND sessions.generated_lesson_json IS NOT NULL
            """
        ).fetchall()
        now = _now_iso()
        for row in rows:
            try:
                generated_lesson = json.loads(str(row["generated_lesson_json"]))
                content_hash = lesson_audio_content_hash(generated_lesson)
            except (TypeError, json.JSONDecodeError, ValueError):
                continue
            cursor = connection.execute(
                """
                INSERT INTO lesson_audio_jobs (
                    user_id, lesson_id, content_hash, status, attempt_count, next_attempt_at,
                    provider, model, voice_config_version, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, 'succeeded', 0, ?, 'gemini', ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, lesson_id, content_hash) DO NOTHING
                """,
                (
                    int(row["user_id"]), str(row["lesson_id"]), content_hash, now,
                    DEFAULT_TTS_MODEL, VOICE_CONFIG_VERSION, now, now, now,
                ),
            )
            job = connection.execute(
                """
                SELECT id FROM lesson_audio_jobs
                WHERE user_id = ? AND lesson_id = ? AND content_hash = ?
                """,
                (int(row["user_id"]), str(row["lesson_id"]), content_hash),
            ).fetchone()
            if cursor is not None and job is not None:
                connection.execute(
                    """
                    UPDATE lesson_audio_cache
                    SET content_hash = ?, job_id = ?, model = ?, voice_config_version = ?
                    WHERE user_id = ? AND lesson_id = ?
                    """,
                    (
                        content_hash, int(job["id"]), DEFAULT_TTS_MODEL, VOICE_CONFIG_VERSION,
                        int(row["user_id"]), str(row["lesson_id"]),
                    ),
                )

    def _apply_migration(self, connection: sqlite3.Connection, version: int, sql: str) -> None:
        row = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?",
            (version,),
        ).fetchone()
        if row is not None:
            return

        connection.executescript(sql)
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, _now_iso()),
        )

    def find_or_create_user(self, apple_sub: str, email: str | None) -> User:
        now = _now_iso()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, apple_sub, email FROM users WHERE apple_sub = ?",
                (apple_sub,),
            ).fetchone()
            if row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO users (apple_sub, email, created_at, last_seen_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (apple_sub, email, now, now),
                )
                connection.commit()
                return User(id=int(cursor.lastrowid), apple_sub=apple_sub, email=email)

            connection.execute(
                """
                UPDATE users
                SET email = COALESCE(email, ?), last_seen_at = ?
                WHERE apple_sub = ?
                """,
                (email, now, apple_sub),
            )
            connection.commit()
            return User(id=int(row["id"]), apple_sub=row["apple_sub"], email=row["email"] or email)

    def user_exists(self, apple_sub: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM users WHERE apple_sub = ? LIMIT 1",
                (apple_sub,),
            ).fetchone()
            return row is not None

    def find_user_by_apple_sub(self, apple_sub: str) -> User | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, apple_sub, email FROM users WHERE apple_sub = ?",
                (apple_sub,),
            ).fetchone()
            if row is None:
                return None
            return User(id=int(row["id"]), apple_sub=row["apple_sub"], email=row["email"])

    def record_openai_usage(self, event: dict[str, Any]) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO openai_usage_events (
                    user_id, request_role, request_name, source_id, model, prompt_version,
                    prompt_cache_key, input_tokens, cached_tokens, cache_write_tokens,
                    ordinary_input_tokens, output_tokens, reasoning_tokens, total_tokens,
                    estimated_cost_usd, actual_cost_usd, effective_input_cost_usd,
                    uncached_input_cost_usd, net_cache_savings_usd, elapsed_ms,
                    openai_request_id, provider_response_id, created_at, raw_usage_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(event["user_id"]),
                    str(event["request_role"]),
                    str(event["request_name"]),
                    event.get("source_id"),
                    str(event["model"]),
                    event.get("prompt_version"),
                    event.get("prompt_cache_key"),
                    event.get("input_tokens"),
                    event.get("cached_tokens"),
                    event.get("cache_write_tokens"),
                    event.get("ordinary_input_tokens"),
                    event.get("output_tokens"),
                    event.get("reasoning_tokens"),
                    event.get("total_tokens"),
                    event.get("estimated_cost_usd"),
                    event.get("actual_cost_usd"),
                    event.get("effective_input_cost_usd"),
                    event.get("uncached_input_cost_usd"),
                    event.get("net_cache_savings_usd"),
                    int(event.get("elapsed_ms") or 0),
                    event.get("openai_request_id"),
                    event.get("provider_response_id"),
                    event.get("created_at") or _now_iso(),
                    _dump_json(event.get("raw_usage") or {}),
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    def usage_dashboard_summary(
        self,
        *,
        start_time: str,
        end_time: str,
        roles: list[str] | None = None,
        event_limit: int = 250,
    ) -> UsageDashboardSummary:
        role_filter = [role for role in (roles or []) if role]
        role_clause = ""
        role_params: list[object] = []
        if role_filter:
            placeholders = ",".join("?" for _ in role_filter)
            role_clause = f" AND openai_usage_events.request_role IN ({placeholders})"
            role_params.extend(role_filter)

        range_params: list[object] = [start_time, end_time, *role_params]
        with self._connect() as connection:
            totals_row = connection.execute(
                f"""
                SELECT
                    COUNT(*) AS request_count,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
                    COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
                    COALESCE(SUM(ordinary_input_tokens), 0) AS ordinary_input_tokens,
                    CASE WHEN COALESCE(SUM(input_tokens), 0) > 0
                        THEN 1.0 * COALESCE(SUM(cached_tokens), 0) / SUM(input_tokens)
                        ELSE 0.0 END AS cache_read_ratio,
                    CASE WHEN COALESCE(SUM(input_tokens), 0) > 0
                        THEN 1.0 * COALESCE(SUM(cache_write_tokens), 0) / SUM(input_tokens)
                        ELSE 0.0 END AS cache_write_ratio,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0.0) AS estimated_cost_usd,
                    COALESCE(SUM(actual_cost_usd), 0.0) AS actual_cost_usd,
                    COALESCE(SUM(effective_input_cost_usd), 0.0) AS effective_input_cost_usd,
                    COALESCE(SUM(uncached_input_cost_usd), 0.0) AS uncached_input_cost_usd,
                    COALESCE(SUM(net_cache_savings_usd), 0.0) AS net_cache_savings_usd,
                    CASE WHEN COALESCE(SUM(uncached_input_cost_usd), 0.0) > 0
                        THEN COALESCE(SUM(net_cache_savings_usd), 0.0) / SUM(uncached_input_cost_usd)
                        ELSE 0.0 END AS net_cache_savings_ratio
                FROM openai_usage_events
                WHERE created_at >= ? AND created_at < ?
                {role_clause}
                """,
                range_params,
            ).fetchone()
            user_rows = connection.execute(
                f"""
                SELECT
                    users.id AS user_id,
                    users.email AS email,
                    COUNT(openai_usage_events.id) AS request_count,
                    COALESCE(SUM(openai_usage_events.input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(openai_usage_events.cached_tokens), 0) AS cached_tokens,
                    COALESCE(SUM(openai_usage_events.cache_write_tokens), 0) AS cache_write_tokens,
                    COALESCE(SUM(openai_usage_events.ordinary_input_tokens), 0) AS ordinary_input_tokens,
                    CASE WHEN COALESCE(SUM(openai_usage_events.input_tokens), 0) > 0
                        THEN 1.0 * COALESCE(SUM(openai_usage_events.cached_tokens), 0) /
                            SUM(openai_usage_events.input_tokens)
                        ELSE 0.0 END AS cache_read_ratio,
                    CASE WHEN COALESCE(SUM(openai_usage_events.input_tokens), 0) > 0
                        THEN 1.0 * COALESCE(SUM(openai_usage_events.cache_write_tokens), 0) /
                            SUM(openai_usage_events.input_tokens)
                        ELSE 0.0 END AS cache_write_ratio,
                    COALESCE(SUM(openai_usage_events.output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(openai_usage_events.reasoning_tokens), 0) AS reasoning_tokens,
                    COALESCE(SUM(openai_usage_events.total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(openai_usage_events.estimated_cost_usd), 0.0) AS estimated_cost_usd,
                    COALESCE(SUM(openai_usage_events.actual_cost_usd), 0.0) AS actual_cost_usd,
                    COALESCE(SUM(openai_usage_events.effective_input_cost_usd), 0.0) AS effective_input_cost_usd,
                    COALESCE(SUM(openai_usage_events.uncached_input_cost_usd), 0.0) AS uncached_input_cost_usd,
                    COALESCE(SUM(openai_usage_events.net_cache_savings_usd), 0.0) AS net_cache_savings_usd,
                    CASE WHEN COALESCE(SUM(openai_usage_events.uncached_input_cost_usd), 0.0) > 0
                        THEN COALESCE(SUM(openai_usage_events.net_cache_savings_usd), 0.0) /
                            SUM(openai_usage_events.uncached_input_cost_usd)
                        ELSE 0.0 END AS net_cache_savings_ratio
                FROM users
                LEFT JOIN openai_usage_events
                    ON users.id = openai_usage_events.user_id
                    AND openai_usage_events.created_at >= ?
                    AND openai_usage_events.created_at < ?
                    {role_clause}
                GROUP BY users.id, users.email
                ORDER BY estimated_cost_usd DESC, total_tokens DESC, request_count DESC, users.id ASC
                """,
                range_params,
            ).fetchall()
            user_model_rows = connection.execute(
                f"""
                SELECT
                    users.id AS user_id,
                    openai_usage_events.model AS model,
                    COUNT(openai_usage_events.id) AS request_count,
                    COALESCE(SUM(openai_usage_events.input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(openai_usage_events.cached_tokens), 0) AS cached_tokens,
                    COALESCE(SUM(openai_usage_events.cache_write_tokens), 0) AS cache_write_tokens,
                    COALESCE(SUM(openai_usage_events.ordinary_input_tokens), 0) AS ordinary_input_tokens,
                    CASE WHEN COALESCE(SUM(openai_usage_events.input_tokens), 0) > 0
                        THEN 1.0 * COALESCE(SUM(openai_usage_events.cached_tokens), 0) /
                            SUM(openai_usage_events.input_tokens)
                        ELSE 0.0 END AS cache_read_ratio,
                    CASE WHEN COALESCE(SUM(openai_usage_events.input_tokens), 0) > 0
                        THEN 1.0 * COALESCE(SUM(openai_usage_events.cache_write_tokens), 0) /
                            SUM(openai_usage_events.input_tokens)
                        ELSE 0.0 END AS cache_write_ratio,
                    COALESCE(SUM(openai_usage_events.output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(openai_usage_events.reasoning_tokens), 0) AS reasoning_tokens,
                    COALESCE(SUM(openai_usage_events.total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(openai_usage_events.estimated_cost_usd), 0.0) AS estimated_cost_usd,
                    COALESCE(SUM(openai_usage_events.actual_cost_usd), 0.0) AS actual_cost_usd,
                    COALESCE(SUM(openai_usage_events.effective_input_cost_usd), 0.0) AS effective_input_cost_usd,
                    COALESCE(SUM(openai_usage_events.uncached_input_cost_usd), 0.0) AS uncached_input_cost_usd,
                    COALESCE(SUM(openai_usage_events.net_cache_savings_usd), 0.0) AS net_cache_savings_usd,
                    CASE WHEN COALESCE(SUM(openai_usage_events.uncached_input_cost_usd), 0.0) > 0
                        THEN COALESCE(SUM(openai_usage_events.net_cache_savings_usd), 0.0) /
                            SUM(openai_usage_events.uncached_input_cost_usd)
                        ELSE 0.0 END AS net_cache_savings_ratio
                FROM users
                LEFT JOIN openai_usage_events
                    ON users.id = openai_usage_events.user_id
                    AND openai_usage_events.created_at >= ?
                    AND openai_usage_events.created_at < ?
                    {role_clause}
                GROUP BY users.id, openai_usage_events.model
                ORDER BY users.id ASC, openai_usage_events.model ASC
                """,
                range_params,
            ).fetchall()
            role_rows = connection.execute(
                f"""
                SELECT
                    request_role,
                    model,
                    COUNT(*) AS request_count,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
                    COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
                    COALESCE(SUM(ordinary_input_tokens), 0) AS ordinary_input_tokens,
                    CASE WHEN COALESCE(SUM(input_tokens), 0) > 0
                        THEN 1.0 * COALESCE(SUM(cached_tokens), 0) / SUM(input_tokens)
                        ELSE 0.0 END AS cache_read_ratio,
                    CASE WHEN COALESCE(SUM(input_tokens), 0) > 0
                        THEN 1.0 * COALESCE(SUM(cache_write_tokens), 0) / SUM(input_tokens)
                        ELSE 0.0 END AS cache_write_ratio,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0.0) AS estimated_cost_usd,
                    COALESCE(SUM(actual_cost_usd), 0.0) AS actual_cost_usd,
                    COALESCE(SUM(effective_input_cost_usd), 0.0) AS effective_input_cost_usd,
                    COALESCE(SUM(uncached_input_cost_usd), 0.0) AS uncached_input_cost_usd,
                    COALESCE(SUM(net_cache_savings_usd), 0.0) AS net_cache_savings_usd,
                    CASE WHEN COALESCE(SUM(uncached_input_cost_usd), 0.0) > 0
                        THEN COALESCE(SUM(net_cache_savings_usd), 0.0) / SUM(uncached_input_cost_usd)
                        ELSE 0.0 END AS net_cache_savings_ratio
                FROM openai_usage_events
                WHERE created_at >= ? AND created_at < ?
                {role_clause}
                GROUP BY request_role, model
                ORDER BY request_role ASC, estimated_cost_usd DESC, total_tokens DESC
                """,
                range_params,
            ).fetchall()
            event_rows = connection.execute(
                f"""
                SELECT
                    openai_usage_events.created_at,
                    users.id AS user_id,
                    users.email AS email,
                    openai_usage_events.request_role,
                    openai_usage_events.request_name,
                    openai_usage_events.source_id,
                    openai_usage_events.model,
                    openai_usage_events.input_tokens,
                    openai_usage_events.cached_tokens,
                    openai_usage_events.cache_write_tokens,
                    openai_usage_events.ordinary_input_tokens,
                    CASE WHEN COALESCE(openai_usage_events.input_tokens, 0) > 0
                        THEN 1.0 * COALESCE(openai_usage_events.cached_tokens, 0) /
                            openai_usage_events.input_tokens
                        ELSE 0.0 END AS cache_read_ratio,
                    CASE WHEN COALESCE(openai_usage_events.input_tokens, 0) > 0
                        THEN 1.0 * COALESCE(openai_usage_events.cache_write_tokens, 0) /
                            openai_usage_events.input_tokens
                        ELSE 0.0 END AS cache_write_ratio,
                    openai_usage_events.output_tokens,
                    openai_usage_events.reasoning_tokens,
                    openai_usage_events.total_tokens,
                    openai_usage_events.estimated_cost_usd,
                    openai_usage_events.actual_cost_usd,
                    openai_usage_events.effective_input_cost_usd,
                    openai_usage_events.uncached_input_cost_usd,
                    openai_usage_events.net_cache_savings_usd,
                    CASE WHEN COALESCE(openai_usage_events.uncached_input_cost_usd, 0.0) > 0
                        THEN COALESCE(openai_usage_events.net_cache_savings_usd, 0.0) /
                            openai_usage_events.uncached_input_cost_usd
                        ELSE 0.0 END AS net_cache_savings_ratio,
                    openai_usage_events.elapsed_ms
                FROM openai_usage_events
                JOIN users ON users.id = openai_usage_events.user_id
                WHERE openai_usage_events.created_at >= ? AND openai_usage_events.created_at < ?
                {role_clause}
                ORDER BY openai_usage_events.created_at DESC
                LIMIT ?
                """,
                [*range_params, event_limit],
            ).fetchall()

        return UsageDashboardSummary(
            start_time=start_time,
            end_time=end_time,
            roles=role_filter,
            totals=_usage_row_dict(totals_row),
            users=[_usage_row_dict(row) for row in user_rows],
            user_models=[
                _usage_row_dict(row)
                for row in user_model_rows
                if row["model"] is not None
            ],
            role_totals=[_usage_row_dict(row) for row in role_rows],
            events=[_usage_row_dict(row) for row in event_rows],
        )

    def list_lesson_sessions(
        self,
        *,
        user_id: int,
        updated_after: str | None = None,
        limit: int = 500,
    ) -> list[LessonSession]:
        session_query = """
            SELECT lesson_sessions.*,
                (EXISTS (
                    SELECT 1
                    FROM lesson_audio_cache
                    WHERE lesson_audio_cache.user_id = lesson_sessions.user_id
                        AND lesson_audio_cache.lesson_id = lesson_sessions.lesson_id
                ) OR EXISTS (
                    SELECT 1 FROM artifact_audio_cache
                    WHERE artifact_audio_cache.lesson_artifact_id = lesson_sessions.lesson_artifact_id
                )) AS has_audio
            FROM lesson_sessions
            WHERE user_id = ? AND deleted_at IS NULL
        """
        params: list[object] = [user_id]
        if updated_after:
            session_query += " AND server_updated_at > ?"
            params.append(updated_after)

        with self._connect() as connection:
            session_rows = connection.execute(session_query, params).fetchall()
            progress_query = """
                SELECT lesson_progress.*,
                    EXISTS (
                        SELECT 1
                        FROM lesson_audio_cache
                        WHERE lesson_audio_cache.user_id = lesson_progress.user_id
                            AND lesson_audio_cache.lesson_id = lesson_progress.lesson_id
                    ) AS has_audio
                FROM lesson_progress
                LEFT JOIN lesson_sessions
                    ON lesson_sessions.user_id = lesson_progress.user_id
                    AND lesson_sessions.lesson_id = lesson_progress.lesson_id
                    AND lesson_sessions.deleted_at IS NULL
                WHERE lesson_progress.user_id = ?
                    AND lesson_progress.is_completed = 1
                    AND lesson_sessions.id IS NULL
            """
            progress_params: list[object] = [user_id]
            if updated_after:
                progress_query += " AND lesson_progress.server_updated_at > ?"
                progress_params.append(updated_after)
            progress_rows = connection.execute(progress_query, progress_params).fetchall()

        sessions = [self._lesson_session_from_row(row) for row in session_rows]
        sessions.extend(_progress_row_as_completed_session(row) for row in progress_rows)
        return sorted(sessions, key=lambda session: session.server_updated_at)[:limit]

    def get_shared_lesson_artifact(self, *, lesson_id: str, recipe_fingerprint: str) -> LessonArtifact | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM lesson_artifacts
                WHERE lesson_id = ? AND recipe_fingerprint = ? AND scope = 'shared'
                    AND invalidated_at IS NULL
                """,
                (lesson_id, recipe_fingerprint),
            ).fetchone()
        return self._lesson_artifact_from_row(row) if row is not None else None

    def get_lesson_artifact(self, artifact_id: str) -> LessonArtifact | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM lesson_artifacts WHERE id = ?", (artifact_id,)).fetchone()
        return self._lesson_artifact_from_row(row) if row is not None else None

    def lesson_artifact_for_user(self, *, artifact_id: str, user_id: int) -> LessonArtifact | None:
        artifact = self.get_lesson_artifact(artifact_id)
        if artifact is None:
            return None
        if artifact.scope == "private" and artifact.owner_user_id != user_id:
            return None
        return artifact

    def invalidate_lesson_artifact(self, *, artifact_id: str, reason: str) -> bool:
        now = _now_iso()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE lesson_artifacts
                SET invalidated_at = ?, invalidation_reason = ?
                WHERE id = ? AND invalidated_at IS NULL
                """,
                (now, reason[:500], artifact_id),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    """
                    UPDATE lesson_generation_jobs
                    SET status = 'superseded', artifact_id = NULL, updated_at = ?, completed_at = ?
                    WHERE artifact_id = ? AND status = 'succeeded'
                    """,
                    (now, now, artifact_id),
                )
            connection.commit()
        return cursor.rowcount == 1

    def unreferenced_private_artifacts(self, *, created_before: str, limit: int = 500) -> list[LessonArtifact]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT artifacts.*
                FROM lesson_artifacts AS artifacts
                WHERE artifacts.scope = 'private' AND artifacts.created_at < ?
                  AND NOT EXISTS (
                    SELECT 1 FROM lesson_sessions AS sessions
                    WHERE sessions.lesson_artifact_id = artifacts.id AND sessions.deleted_at IS NULL
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM artifact_audio_jobs AS jobs
                    WHERE jobs.lesson_artifact_id = artifacts.id
                      AND jobs.status IN ('pending', 'running')
                  )
                ORDER BY artifacts.created_at
                LIMIT ?
                """,
                (created_before, max(1, min(limit, 5_000))),
            ).fetchall()
        return [self._lesson_artifact_from_row(row) for row in rows]

    def delete_unreferenced_private_artifact(self, *, artifact_id: str) -> list[str]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            referenced = connection.execute(
                """
                SELECT 1 FROM lesson_artifacts AS artifacts
                WHERE artifacts.id = ? AND artifacts.scope = 'private'
                  AND (
                    EXISTS (SELECT 1 FROM lesson_sessions AS sessions
                            WHERE sessions.lesson_artifact_id = artifacts.id AND sessions.deleted_at IS NULL)
                    OR EXISTS (SELECT 1 FROM artifact_audio_jobs AS jobs
                               WHERE jobs.lesson_artifact_id = artifacts.id
                                 AND jobs.status IN ('pending', 'running'))
                  )
                """,
                (artifact_id,),
            ).fetchone()
            if referenced is not None:
                connection.commit()
                return []
            paths = [
                str(row["relative_file_path"])
                for row in connection.execute(
                    "SELECT relative_file_path FROM artifact_audio_cache WHERE lesson_artifact_id = ?",
                    (artifact_id,),
                ).fetchall()
            ]
            connection.execute(
                "DELETE FROM lesson_generation_jobs WHERE artifact_id = ? AND status IN ('succeeded', 'failed', 'superseded')",
                (artifact_id,),
            )
            cursor = connection.execute(
                "DELETE FROM lesson_artifacts WHERE id = ? AND scope = 'private'",
                (artifact_id,),
            )
            unreferenced_paths = [
                path
                for path in paths
                if connection.execute(
                    "SELECT 1 FROM artifact_audio_cache WHERE relative_file_path = ? LIMIT 1",
                    (path,),
                ).fetchone()
                is None
            ]
            connection.commit()
        return unreferenced_paths if cursor.rowcount == 1 else []

    def begin_lesson_generation(
        self,
        *,
        lesson_id: str,
        recipe_fingerprint: str,
        recipe: dict[str, Any],
        scope: str,
        requested_by_user_id: int,
        lease_seconds: int = 300,
    ) -> tuple[LessonGenerationJob, bool]:
        if scope not in {"shared", "private"}:
            raise ValueError("Invalid lesson artifact scope.")
        now_dt = datetime.now(UTC)
        now = _iso(now_dt)
        lease_expires_at = _iso(now_dt + timedelta(seconds=lease_seconds))
        owner_user_id = requested_by_user_id if scope == "private" else None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = None
            if scope == "shared":
                row = connection.execute(
                    """
                    SELECT * FROM lesson_generation_jobs
                    WHERE lesson_id = ? AND recipe_fingerprint = ? AND scope = 'shared'
                    """,
                    (lesson_id, recipe_fingerprint),
                ).fetchone()
            if row is not None:
                status_value = str(row["status"])
                lease_value = str(row["lease_expires_at"] or "")
                if status_value == "succeeded" or (status_value == "running" and lease_value > now):
                    connection.commit()
                    return self._lesson_generation_job_from_row(row), False
                connection.execute(
                    """
                    UPDATE lesson_generation_jobs
                    SET status = 'running', attempt_count = attempt_count + 1,
                        lease_expires_at = ?, requested_by_user_id = ?,
                        last_error_code = NULL, last_error_summary = NULL, updated_at = ?, completed_at = NULL
                    WHERE id = ?
                    """,
                    (lease_expires_at, requested_by_user_id, now, int(row["id"])),
                )
                claimed = connection.execute(
                    "SELECT * FROM lesson_generation_jobs WHERE id = ?", (int(row["id"]),)
                ).fetchone()
                connection.commit()
                return self._lesson_generation_job_from_row(claimed), True

            cursor = connection.execute(
                """
                INSERT INTO lesson_generation_jobs (
                    lesson_id, recipe_fingerprint, recipe_json, scope, owner_user_id,
                    requested_by_user_id, status, attempt_count, lease_expires_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'running', 1, ?, ?, ?)
                """,
                (
                    lesson_id, recipe_fingerprint, _dump_json(recipe), scope, owner_user_id,
                    requested_by_user_id, lease_expires_at, now, now,
                ),
            )
            job_id = int(cursor.lastrowid)
            claimed = connection.execute(
                "SELECT * FROM lesson_generation_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            connection.commit()
        return self._lesson_generation_job_from_row(claimed), True

    def complete_lesson_generation(
        self,
        *,
        job: LessonGenerationJob,
        generated_lesson: dict[str, Any],
        lesson_content_hash: str,
        requested_model: str,
        provider_model: str | None,
        reasoning_effort: str,
        provider_request_id: str | None,
    ) -> LessonArtifact:
        now = _now_iso()
        artifact_id = str(uuid.uuid4())
        stored_lesson = dict(generated_lesson)
        stored_lesson.update(
            {
                "artifact_id": artifact_id,
                "artifact_scope": job.scope,
                "recipe_fingerprint": job.recipe_fingerprint,
            }
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current_job = connection.execute(
                "SELECT status, attempt_count FROM lesson_generation_jobs WHERE id = ?",
                (job.id,),
            ).fetchone()
            if (
                current_job is None
                or str(current_job["status"]) != "running"
                or int(current_job["attempt_count"]) != job.attempt_count
            ):
                connection.commit()
                raise RuntimeError("Lesson generation lease expired.")
            existing = None
            if job.scope == "shared":
                existing = connection.execute(
                    """
                    SELECT * FROM lesson_artifacts
                    WHERE lesson_id = ? AND recipe_fingerprint = ? AND scope = 'shared'
                        AND invalidated_at IS NULL
                    """,
                    (job.lesson_id, job.recipe_fingerprint),
                ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO lesson_artifacts (
                        id, lesson_id, scope, owner_user_id, recipe_fingerprint, recipe_json,
                        lesson_content_hash, generated_lesson_json, requested_model, provider_model,
                        reasoning_effort, provider_request_id, created_by_user_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact_id, job.lesson_id, job.scope, job.owner_user_id,
                        job.recipe_fingerprint, _dump_json(job.recipe), lesson_content_hash,
                        _dump_json(stored_lesson), requested_model, provider_model,
                        reasoning_effort, provider_request_id, job.requested_by_user_id, now,
                    ),
                )
                artifact_row = connection.execute(
                    "SELECT * FROM lesson_artifacts WHERE id = ?", (artifact_id,)
                ).fetchone()
            else:
                artifact_row = existing
                artifact_id = str(existing["id"])
            connection.execute(
                """
                UPDATE lesson_generation_jobs
                SET status = 'succeeded', artifact_id = ?, lease_expires_at = NULL,
                    updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (artifact_id, now, now, job.id),
            )
            connection.commit()
        return self._lesson_artifact_from_row(artifact_row)

    def fail_lesson_generation(
        self, *, job_id: int, attempt_count: int, error_code: str, error_summary: str
    ) -> None:
        now = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE lesson_generation_jobs
                SET status = 'failed', lease_expires_at = NULL, last_error_code = ?,
                    last_error_summary = ?, updated_at = ?, completed_at = ?
                WHERE id = ? AND status = 'running' AND attempt_count = ?
                """,
                (error_code[:80], error_summary[:500], now, now, job_id, attempt_count),
            )
            connection.commit()

    def get_lesson_generation_job(self, *, job_id: int, user_id: int) -> LessonGenerationJob | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM lesson_generation_jobs
                WHERE id = ? AND (scope = 'shared' OR owner_user_id = ?)
                """,
                (job_id, user_id),
            ).fetchone()
        return self._lesson_generation_job_from_row(row) if row is not None else None

    def get_artifact_audio(
        self, *, lesson_artifact_id: str, audio_recipe_fingerprint: str
    ) -> ArtifactAudio | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM artifact_audio_cache
                WHERE lesson_artifact_id = ? AND audio_recipe_fingerprint = ?
                """,
                (lesson_artifact_id, audio_recipe_fingerprint),
            ).fetchone()
        return self._artifact_audio_from_row(row) if row is not None else None

    def delete_artifact_audio(self, *, lesson_artifact_id: str, audio_recipe_fingerprint: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM artifact_audio_cache WHERE lesson_artifact_id = ? AND audio_recipe_fingerprint = ?",
                (lesson_artifact_id, audio_recipe_fingerprint),
            )
            connection.commit()

    def request_artifact_audio_job(
        self,
        *,
        artifact: LessonArtifact,
        requested_by_user_id: int,
        content_hash: str,
        dialogue_text_hash: str,
        audio_recipe_fingerprint: str,
        model: str,
        voice_config_version: str,
        max_queued_per_user: int,
        retry_cooldown_seconds: int,
    ) -> tuple[ArtifactAudioJob | None, ArtifactAudio | None]:
        audio = self.get_artifact_audio(
            lesson_artifact_id=artifact.id, audio_recipe_fingerprint=audio_recipe_fingerprint
        )
        if audio is not None and audio.content_hash == content_hash:
            return None, audio
        now_dt = datetime.now(UTC)
        now = _iso(now_dt)
        cooldown_cutoff = _iso(now_dt - timedelta(seconds=max(retry_cooldown_seconds, 0)))
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM artifact_audio_jobs
                WHERE lesson_artifact_id = ? AND audio_recipe_fingerprint = ?
                """,
                (artifact.id, audio_recipe_fingerprint),
            ).fetchone()
            if row is not None and str(row["status"]) in {"pending", "running"}:
                return self._artifact_audio_job_from_row(row), None
            if row is not None and str(row["status"]) == "failed" and str(row["updated_at"]) > cooldown_cutoff:
                return self._artifact_audio_job_from_row(row), None
            active_count = connection.execute(
                """
                SELECT COUNT(*) AS count FROM artifact_audio_jobs
                WHERE requested_by_user_id = ? AND status IN ('pending', 'running')
                """,
                (requested_by_user_id,),
            ).fetchone()
            if int(active_count["count"] or 0) >= max_queued_per_user:
                raise OverflowError("Too many lesson audio jobs are already queued.")
            connection.execute(
                """
                INSERT INTO artifact_audio_jobs (
                    lesson_artifact_id, requested_by_user_id, lesson_id, content_hash,
                    dialogue_text_hash, audio_recipe_fingerprint, status, attempt_count,
                    next_attempt_at, provider, model, voice_config_version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, 'gemini', ?, ?, ?, ?)
                ON CONFLICT(lesson_artifact_id, audio_recipe_fingerprint) DO UPDATE SET
                    requested_by_user_id = excluded.requested_by_user_id,
                    content_hash = excluded.content_hash,
                    dialogue_text_hash = excluded.dialogue_text_hash,
                    status = 'pending', attempt_count = 0, next_attempt_at = excluded.next_attempt_at,
                    lease_expires_at = NULL, model = excluded.model,
                    voice_config_version = excluded.voice_config_version,
                    last_error_code = NULL, last_error_summary = NULL,
                    updated_at = excluded.updated_at, completed_at = NULL
                WHERE artifact_audio_jobs.status IN ('failed', 'superseded', 'succeeded')
                """,
                (
                    artifact.id, requested_by_user_id, artifact.lesson_id, content_hash,
                    dialogue_text_hash, audio_recipe_fingerprint, now, model,
                    voice_config_version, now, now,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM artifact_audio_jobs
                WHERE lesson_artifact_id = ? AND audio_recipe_fingerprint = ?
                """,
                (artifact.id, audio_recipe_fingerprint),
            ).fetchone()
            connection.commit()
        return self._artifact_audio_job_from_row(row), None

    def artifact_audio_status(
        self,
        *,
        artifact: LessonArtifact,
        content_hash: str,
        audio_recipe_fingerprint: str,
    ) -> tuple[str, ArtifactAudioJob | None, ArtifactAudio | None]:
        audio = self.get_artifact_audio(
            lesson_artifact_id=artifact.id, audio_recipe_fingerprint=audio_recipe_fingerprint
        )
        if audio is not None and audio.content_hash == content_hash:
            return "ready", None, audio
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM artifact_audio_jobs
                WHERE lesson_artifact_id = ? AND audio_recipe_fingerprint = ?
                """,
                (artifact.id, audio_recipe_fingerprint),
            ).fetchone()
        if row is None or str(row["status"]) in {"succeeded", "superseded"}:
            return "missing", None, None
        return str(row["status"]), self._artifact_audio_job_from_row(row), None

    def claim_artifact_audio_job(self, *, lease_seconds: int) -> ArtifactAudioJob | None:
        now_dt = datetime.now(UTC)
        now = _iso(now_dt)
        lease_expires_at = _iso(now_dt + timedelta(seconds=lease_seconds))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM artifact_audio_jobs
                WHERE (status = 'pending' AND next_attempt_at <= ?)
                   OR (status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                ORDER BY next_attempt_at, created_at LIMIT 1
                """,
                (now, now),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE artifact_audio_jobs
                SET status = 'running', attempt_count = attempt_count + 1,
                    lease_expires_at = ?, updated_at = ? WHERE id = ?
                """,
                (lease_expires_at, now, int(row["id"])),
            )
            claimed = connection.execute(
                "SELECT * FROM artifact_audio_jobs WHERE id = ?", (int(row["id"]),)
            ).fetchone()
            connection.commit()
        return self._artifact_audio_job_from_row(claimed)

    def complete_artifact_audio_job(
        self, *, job: ArtifactAudioJob, relative_file_path: str, byte_count: int
    ) -> bool:
        now = _now_iso()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT status, attempt_count FROM artifact_audio_jobs WHERE id = ?", (job.id,)
            ).fetchone()
            if (
                current is None
                or str(current["status"]) != "running"
                or int(current["attempt_count"]) != job.attempt_count
            ):
                connection.commit()
                return False
            connection.execute(
                """
                INSERT INTO artifact_audio_cache (
                    lesson_artifact_id, audio_recipe_fingerprint, content_hash,
                    dialogue_text_hash, relative_file_path, content_type, byte_count,
                    provider, model, voice_config_version, generated_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'audio/wav', ?, 'gemini', ?, ?, ?, ?, ?)
                ON CONFLICT(lesson_artifact_id, audio_recipe_fingerprint) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    relative_file_path = excluded.relative_file_path,
                    byte_count = excluded.byte_count, model = excluded.model,
                    voice_config_version = excluded.voice_config_version,
                    generated_at = excluded.generated_at, updated_at = excluded.updated_at
                """,
                (
                    job.lesson_artifact_id, job.audio_recipe_fingerprint, job.content_hash,
                    job.dialogue_text_hash, relative_file_path, byte_count, job.model, job.voice_config_version,
                    now, now, now,
                ),
            )
            connection.execute(
                """
                UPDATE artifact_audio_jobs
                SET status = 'succeeded', lease_expires_at = NULL, updated_at = ?, completed_at = ?
                WHERE id = ? AND status = 'running' AND attempt_count = ?
                """,
                (now, now, job.id, job.attempt_count),
            )
            connection.commit()
        return True

    def fail_artifact_audio_job(
        self,
        *,
        job: ArtifactAudioJob,
        error_code: str,
        error_summary: str,
        retryable: bool,
        max_attempts: int,
        retry_delay_seconds: float,
    ) -> str:
        now_dt = datetime.now(UTC)
        should_retry = retryable and job.attempt_count < max_attempts
        next_status = "pending" if should_retry else "failed"
        next_attempt = _iso(now_dt + timedelta(seconds=max(retry_delay_seconds, 0)))
        now = _iso(now_dt)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE artifact_audio_jobs
                SET status = ?, next_attempt_at = ?, lease_expires_at = NULL,
                    last_error_code = ?, last_error_summary = ?, updated_at = ?,
                    completed_at = CASE WHEN ? = 'failed' THEN ? ELSE NULL END
                WHERE id = ? AND status = 'running' AND attempt_count = ?
                """,
                (
                    next_status, next_attempt, error_code[:80], error_summary[:500], now,
                    next_status, now, job.id, job.attempt_count,
                ),
            )
            connection.commit()
        return next_status

    def supersede_artifact_audio_job(self, job_id: int) -> None:
        now = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE artifact_audio_jobs
                SET status = 'superseded', lease_expires_at = NULL, updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (now, now, job_id),
            )
            connection.commit()

    def get_lesson_session(self, *, user_id: int, lesson_id: str) -> LessonSession | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT lesson_sessions.*,
                    (EXISTS (
                        SELECT 1
                        FROM lesson_audio_cache
                        WHERE lesson_audio_cache.user_id = lesson_sessions.user_id
                            AND lesson_audio_cache.lesson_id = lesson_sessions.lesson_id
                    ) OR EXISTS (
                        SELECT 1 FROM artifact_audio_cache
                        WHERE artifact_audio_cache.lesson_artifact_id = lesson_sessions.lesson_artifact_id
                    )) AS has_audio
                FROM lesson_sessions
                WHERE user_id = ? AND lesson_id = ? AND deleted_at IS NULL
                """,
                (user_id, lesson_id),
            ).fetchone()
            if row is None:
                return None
            return self._lesson_session_from_row(row)

    def upsert_lesson_session(
        self,
        *,
        user_id: int,
        lesson_id: str,
        state: dict[str, Any],
        generated_lesson: dict[str, Any] | None,
        messages: list[dict[str, Any]],
        chat_summary: dict[str, Any] | None,
        client_updated_at: str,
        base_server_updated_at: str | None,
        reset_generation: bool,
        lesson_artifact_id: str | None = None,
        evaluation_snapshot: dict[str, Any] | None = None,
    ) -> LessonSession:
        now = _now_iso()
        status = _status_from_state(state)
        is_completed = bool(state.get("is_completed")) or status == "completed"

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM lesson_sessions
                WHERE user_id = ? AND lesson_id = ? AND deleted_at IS NULL
                """,
                (user_id, lesson_id),
            ).fetchone()
            existing = self._lesson_session_from_row(row) if row is not None else None

            if existing is not None:
                base_matches = base_server_updated_at == existing.server_updated_at
                existing_completed = existing.is_completed or existing.status == "completed"

                if reset_generation and not base_matches:
                    raise LessonSessionConflict(existing)
                if not base_matches and not (is_completed and not existing_completed):
                    raise LessonSessionConflict(existing)

            completed_at = _completed_at(existing, is_completed, state, now)
            state_json = _dump_json(state)
            generated_lesson_json = _dump_json(generated_lesson) if generated_lesson is not None else None
            messages_json = _dump_json(messages)
            chat_summary_json = _dump_json(chat_summary) if chat_summary is not None else None

            if existing is None:
                connection.execute(
                    """
                    INSERT INTO lesson_sessions (
                        user_id,
                        lesson_id,
                        state_json,
                        generated_lesson_json,
                        lesson_artifact_id,
                        messages_json,
                        chat_summary_json,
                        status,
                        is_completed,
                        completed_at,
                        client_updated_at,
                        server_updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        lesson_id,
                        state_json,
                        generated_lesson_json,
                        lesson_artifact_id,
                        messages_json,
                        chat_summary_json,
                        status,
                        int(is_completed),
                        completed_at,
                        client_updated_at,
                        now,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE lesson_sessions
                    SET state_json = ?,
                        generated_lesson_json = ?,
                        lesson_artifact_id = ?,
                        messages_json = ?,
                        chat_summary_json = ?,
                        status = ?,
                        is_completed = ?,
                        completed_at = ?,
                        client_updated_at = ?,
                        server_updated_at = ?,
                        deleted_at = NULL
                    WHERE user_id = ? AND lesson_id = ?
                    """,
                    (
                        state_json,
                        generated_lesson_json,
                        lesson_artifact_id,
                        messages_json,
                        chat_summary_json,
                        status,
                        int(is_completed),
                        completed_at,
                        client_updated_at,
                        now,
                        user_id,
                        lesson_id,
                    ),
                )

            self._upsert_lesson_progress(
                connection,
                user_id=user_id,
                lesson_id=lesson_id,
                status=status,
                is_completed=is_completed,
                completed_at=completed_at,
                client_updated_at=client_updated_at,
                server_updated_at=now,
            )
            old_hash = _generated_lesson_hash(existing.generated_lesson if existing is not None else None)
            new_hash = _generated_lesson_hash(generated_lesson)
            if reset_generation or old_hash != new_hash:
                self._supersede_lesson_audio_jobs(
                    connection,
                    user_id=user_id,
                    lesson_id=lesson_id,
                    current_content_hash=new_hash,
                    now=now,
                )
                self._delete_lesson_audio(connection, user_id=user_id, lesson_id=lesson_id)
            existing_completed = existing is not None and (existing.is_completed or existing.status == "completed")
            if is_completed and not existing_completed and evaluation_snapshot is not None:
                self._enqueue_evaluation_job(
                    connection,
                    user_id=user_id,
                    source_kind="lesson",
                    source_id=lesson_id,
                    snapshot=evaluation_snapshot,
                    prompt_version="evaluator_v3",
                )
            connection.commit()

        session = self.get_lesson_session(user_id=user_id, lesson_id=lesson_id)
        if session is None:
            raise RuntimeError("Lesson session upsert did not return a row.")
        return session

    def store_lesson_audio(
        self,
        *,
        user_id: int,
        lesson_id: str,
        audio_data: bytes,
        content_type: str = "audio/wav",
        content_hash: str | None = None,
        job_id: int | None = None,
        model: str = DEFAULT_TTS_MODEL,
        voice_config_version: str = VOICE_CONFIG_VERSION,
    ) -> LessonAudio | None:
        now = _now_iso()
        with self._connect() as connection:
            session = connection.execute(
                """
                SELECT generated_lesson_json, client_updated_at
                FROM lesson_sessions
                WHERE user_id = ? AND lesson_id = ? AND deleted_at IS NULL
                """,
                (user_id, lesson_id),
            ).fetchone()
            if session is None or not session["generated_lesson_json"]:
                return None

            try:
                generated_lesson = json.loads(str(session["generated_lesson_json"]))
            except (TypeError, json.JSONDecodeError):
                generated_lesson = {}
            try:
                current_content_hash = lesson_audio_content_hash(
                    generated_lesson,
                    model=model,
                    voice_config_version=voice_config_version,
                )
            except ValueError:
                return None
            if content_hash is not None and content_hash != current_content_hash:
                return None
            content_hash = current_content_hash
            generated_at = str(
                generated_lesson.get("generated_at")
                or session["client_updated_at"]
                or now
            )
            connection.execute(
                """
                INSERT INTO lesson_audio_cache (
                    user_id,
                    lesson_id,
                    audio_data,
                    content_type,
                    byte_count,
                    generated_at,
                    content_hash,
                    job_id,
                    model,
                    voice_config_version,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, lesson_id)
                DO UPDATE SET
                    audio_data = excluded.audio_data,
                    content_type = excluded.content_type,
                    byte_count = excluded.byte_count,
                    generated_at = excluded.generated_at,
                    content_hash = excluded.content_hash,
                    job_id = excluded.job_id,
                    model = excluded.model,
                    voice_config_version = excluded.voice_config_version,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    lesson_id,
                    audio_data,
                    content_type,
                    len(audio_data),
                    generated_at,
                    content_hash,
                    job_id,
                    model,
                    voice_config_version,
                    now,
                    now,
                ),
            )
            self._prune_lesson_audio_cache(connection, user_id=user_id, keep_count=5)
            connection.commit()

        audio = self.get_lesson_audio(user_id=user_id, lesson_id=lesson_id)
        if audio is None:
            raise RuntimeError("Lesson audio upsert did not return a row.")
        return audio

    def get_lesson_audio(self, *, user_id: int, lesson_id: str) -> LessonAudio | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT lesson_id, audio_data, content_type, byte_count, generated_at, updated_at,
                       content_hash, job_id, model, voice_config_version
                FROM lesson_audio_cache
                WHERE user_id = ? AND lesson_id = ?
                """,
                (user_id, lesson_id),
            ).fetchone()
        if row is None:
            return None
        return LessonAudio(
            lesson_id=str(row["lesson_id"]),
            audio_data=bytes(row["audio_data"]),
            content_type=str(row["content_type"] or "audio/wav"),
            byte_count=int(row["byte_count"]),
            generated_at=str(row["generated_at"]),
            updated_at=str(row["updated_at"]),
            content_hash=str(row["content_hash"] or ""),
            job_id=int(row["job_id"]) if row["job_id"] is not None else None,
            model=str(row["model"] or DEFAULT_TTS_MODEL),
            voice_config_version=str(row["voice_config_version"] or VOICE_CONFIG_VERSION),
        )

    def current_lesson_audio_identity(self, *, user_id: int, lesson_id: str) -> tuple[dict[str, Any], str] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT generated_lesson_json FROM lesson_sessions
                WHERE user_id = ? AND lesson_id = ? AND deleted_at IS NULL
                """,
                (user_id, lesson_id),
            ).fetchone()
        if row is None or not row["generated_lesson_json"]:
            return None
        try:
            generated_lesson = json.loads(str(row["generated_lesson_json"]))
            content_hash = lesson_audio_content_hash(generated_lesson)
        except (TypeError, json.JSONDecodeError, ValueError):
            return None
        return generated_lesson, content_hash

    def request_lesson_audio_job(
        self,
        *,
        user_id: int,
        lesson_id: str,
        max_queued_per_user: int,
        retry_cooldown_seconds: int,
    ) -> tuple[LessonAudioJob | None, LessonAudio | None]:
        identity = self.current_lesson_audio_identity(user_id=user_id, lesson_id=lesson_id)
        if identity is None:
            raise ValueError("Lesson must contain a valid generated dialogue.")
        _, content_hash = identity
        audio = self.get_lesson_audio(user_id=user_id, lesson_id=lesson_id)
        if audio is not None and audio.content_hash == content_hash:
            return None, audio

        now_dt = datetime.now(UTC)
        now = _iso(now_dt)
        cooldown_cutoff = _iso(now_dt - timedelta(seconds=max(retry_cooldown_seconds, 0)))
        with self._connect() as connection:
            current = connection.execute(
                """
                SELECT * FROM lesson_audio_jobs
                WHERE user_id = ? AND lesson_id = ? AND content_hash = ?
                """,
                (user_id, lesson_id, content_hash),
            ).fetchone()
            if current is not None and str(current["status"]) in {"pending", "running"}:
                return self._lesson_audio_job_from_row(current), None
            if current is not None and str(current["status"]) == "failed" and str(current["updated_at"]) > cooldown_cutoff:
                return self._lesson_audio_job_from_row(current), None

            active_count = connection.execute(
                """
                SELECT COUNT(*) AS count FROM lesson_audio_jobs
                WHERE user_id = ? AND status IN ('pending', 'running')
                """,
                (user_id,),
            ).fetchone()
            if active_count is not None and int(active_count["count"]) >= max_queued_per_user:
                raise OverflowError("Too many lesson audio jobs are already queued.")

            self._supersede_lesson_audio_jobs(
                connection,
                user_id=user_id,
                lesson_id=lesson_id,
                current_content_hash=content_hash,
                now=now,
            )
            connection.execute(
                """
                INSERT INTO lesson_audio_jobs (
                    user_id, lesson_id, content_hash, status, attempt_count, next_attempt_at,
                    lease_expires_at, provider, model, voice_config_version, last_error_code,
                    last_error_summary, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, 'pending', 0, ?, NULL, 'gemini', ?, ?, NULL, NULL, ?, ?, NULL)
                ON CONFLICT(user_id, lesson_id, content_hash) DO UPDATE SET
                    status = 'pending', attempt_count = 0, next_attempt_at = excluded.next_attempt_at,
                    lease_expires_at = NULL, last_error_code = NULL, last_error_summary = NULL,
                    updated_at = excluded.updated_at, completed_at = NULL
                WHERE lesson_audio_jobs.status IN ('failed', 'superseded')
                """,
                (user_id, lesson_id, content_hash, now, DEFAULT_TTS_MODEL, VOICE_CONFIG_VERSION, now, now),
            )
            row = connection.execute(
                """
                SELECT * FROM lesson_audio_jobs
                WHERE user_id = ? AND lesson_id = ? AND content_hash = ?
                """,
                (user_id, lesson_id, content_hash),
            ).fetchone()
            connection.commit()
        if row is None:
            raise RuntimeError("Lesson audio job upsert did not return a row.")
        job = self._lesson_audio_job_from_row(row)
        if job.status == "succeeded":
            audio = self.get_lesson_audio(user_id=user_id, lesson_id=lesson_id)
            if audio is not None and audio.content_hash == content_hash:
                return None, audio
        return job, None

    def lesson_audio_status(self, *, user_id: int, lesson_id: str) -> tuple[str, str | None, LessonAudioJob | None]:
        identity = self.current_lesson_audio_identity(user_id=user_id, lesson_id=lesson_id)
        if identity is None:
            return "missing", None, None
        _, content_hash = identity
        audio = self.get_lesson_audio(user_id=user_id, lesson_id=lesson_id)
        if audio is not None and audio.content_hash == content_hash:
            return "ready", content_hash, None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM lesson_audio_jobs
                WHERE user_id = ? AND lesson_id = ? AND content_hash = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (user_id, lesson_id, content_hash),
            ).fetchone()
        if row is None or str(row["status"]) in {"superseded", "succeeded"}:
            return "missing", content_hash, None
        job = self._lesson_audio_job_from_row(row)
        return job.status, content_hash, job

    def claim_lesson_audio_job(self, *, lease_seconds: int) -> LessonAudioJob | None:
        now_dt = datetime.now(UTC)
        now = _iso(now_dt)
        lease_expires_at = _iso(now_dt + timedelta(seconds=lease_seconds))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM lesson_audio_jobs
                WHERE (status = 'pending' AND next_attempt_at <= ?)
                   OR (status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                ORDER BY next_attempt_at, created_at LIMIT 1
                """,
                (now, now),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE lesson_audio_jobs
                SET status = 'running', attempt_count = attempt_count + 1,
                    lease_expires_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (lease_expires_at, now, int(row["id"])),
            )
            claimed = connection.execute("SELECT * FROM lesson_audio_jobs WHERE id = ?", (int(row["id"]),)).fetchone()
            connection.commit()
        return self._lesson_audio_job_from_row(claimed) if claimed is not None else None

    def complete_lesson_audio_job(self, *, job: LessonAudioJob, audio_data: bytes, content_type: str = "audio/wav") -> bool:
        now = _now_iso()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            session = connection.execute(
                """
                SELECT generated_lesson_json, client_updated_at FROM lesson_sessions
                WHERE user_id = ? AND lesson_id = ? AND deleted_at IS NULL
                """,
                (job.user_id, job.lesson_id),
            ).fetchone()
            try:
                generated_lesson = json.loads(str(session["generated_lesson_json"])) if session else None
                current_hash = lesson_audio_content_hash(
                    generated_lesson,
                    model=job.model,
                    voice_config_version=job.voice_config_version,
                )
            except (TypeError, json.JSONDecodeError, ValueError):
                current_hash = None
            if current_hash != job.content_hash:
                connection.execute(
                    """
                    UPDATE lesson_audio_jobs SET status = 'superseded', lease_expires_at = NULL,
                        updated_at = ?, completed_at = ? WHERE id = ?
                    """,
                    (now, now, job.id),
                )
                connection.commit()
                return False

            generated_at = str(generated_lesson.get("generated_at") or session["client_updated_at"] or now)
            connection.execute(
                """
                INSERT INTO lesson_audio_cache (
                    user_id, lesson_id, audio_data, content_type, byte_count, generated_at,
                    content_hash, job_id, model, voice_config_version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, lesson_id) DO UPDATE SET
                    audio_data = excluded.audio_data, content_type = excluded.content_type,
                    byte_count = excluded.byte_count, generated_at = excluded.generated_at,
                    content_hash = excluded.content_hash, job_id = excluded.job_id,
                    model = excluded.model, voice_config_version = excluded.voice_config_version,
                    updated_at = excluded.updated_at
                """,
                (
                    job.user_id, job.lesson_id, audio_data, content_type, len(audio_data), generated_at,
                    job.content_hash, job.id, job.model, job.voice_config_version, now, now,
                ),
            )
            connection.execute(
                """
                UPDATE lesson_audio_jobs SET status = 'succeeded', lease_expires_at = NULL,
                    last_error_code = NULL, last_error_summary = NULL, updated_at = ?, completed_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (now, now, job.id),
            )
            self._prune_lesson_audio_cache(connection, user_id=job.user_id, keep_count=5)
            connection.commit()
        return True

    def fail_lesson_audio_job(
        self,
        *,
        job: LessonAudioJob,
        error_code: str,
        error_summary: str,
        retryable: bool,
        max_attempts: int,
        retry_delay_seconds: float,
    ) -> str:
        now_dt = datetime.now(UTC)
        should_retry = retryable and job.attempt_count < max_attempts
        next_status = "pending" if should_retry else "failed"
        next_attempt_at = _iso(now_dt + timedelta(seconds=max(retry_delay_seconds, 0)))
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE lesson_audio_jobs SET status = ?, next_attempt_at = ?, lease_expires_at = NULL,
                    last_error_code = ?, last_error_summary = ?, updated_at = ?,
                    completed_at = CASE WHEN ? = 'failed' THEN ? ELSE NULL END
                WHERE id = ?
                """,
                (next_status, next_attempt_at, error_code[:80], error_summary[:300], _iso(now_dt), next_status, _iso(now_dt), job.id),
            )
            connection.commit()
        return next_status

    def supersede_lesson_audio_job(self, job_id: int) -> None:
        now = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE lesson_audio_jobs SET status = 'superseded', lease_expires_at = NULL,
                    updated_at = ?, completed_at = ? WHERE id = ? AND status != 'succeeded'
                """,
                (now, now, job_id),
            )
            connection.commit()

    def lesson_audio_metrics(self) -> dict[str, Any]:
        now_dt = datetime.now(UTC)
        now = _iso(now_dt)
        with self._connect() as connection:
            counts = connection.execute(
                """SELECT status, COUNT(*) AS count FROM lesson_audio_jobs GROUP BY status"""
            ).fetchall()
            oldest = connection.execute(
                """SELECT MIN(created_at) AS oldest FROM lesson_audio_jobs WHERE status = 'pending'"""
            ).fetchone()
            missing = connection.execute(
                """
                SELECT COUNT(*) AS count FROM lesson_sessions AS sessions
                WHERE sessions.generated_lesson_json IS NOT NULL AND sessions.deleted_at IS NULL
                  AND NOT EXISTS (SELECT 1 FROM lesson_audio_cache AS cache
                                  WHERE cache.user_id = sessions.user_id AND cache.lesson_id = sessions.lesson_id)
                  AND NOT EXISTS (SELECT 1 FROM lesson_audio_jobs AS jobs
                                  WHERE jobs.user_id = sessions.user_id AND jobs.lesson_id = sessions.lesson_id
                                    AND jobs.status IN ('pending', 'running'))
                """
            ).fetchone()
            rates = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_jobs,
                    SUM(CASE WHEN attempt_count > 1 THEN 1 ELSE 0 END) AS retried_jobs,
                    SUM(CASE WHEN status IN ('succeeded', 'failed') THEN 1 ELSE 0 END) AS terminal_jobs,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_jobs,
                    AVG(CASE WHEN status = 'succeeded'
                        THEN (julianday(completed_at) - julianday(created_at)) * 86400000.0 END
                    ) AS average_success_latency_ms,
                    SUM(CASE WHEN status = 'running' AND lease_expires_at <= ? THEN 1 ELSE 0 END) AS expired_leases
                FROM lesson_audio_jobs
                """,
                (now,),
            ).fetchone()
            artifact_counts = connection.execute(
                """
                SELECT scope, COUNT(*) AS count
                FROM lesson_artifacts WHERE invalidated_at IS NULL GROUP BY scope
                """
            ).fetchall()
            generation_jobs = connection.execute(
                "SELECT status, COUNT(*) AS count FROM lesson_generation_jobs GROUP BY status"
            ).fetchall()
            artifact_jobs = connection.execute(
                "SELECT status, COUNT(*) AS count FROM artifact_audio_jobs GROUP BY status"
            ).fetchall()
            artifact_audio = connection.execute(
                "SELECT COUNT(*) AS count, COALESCE(SUM(byte_count), 0) AS bytes FROM artifact_audio_cache"
            ).fetchone()
        oldest_value = str(oldest["oldest"]) if oldest and oldest["oldest"] else None
        oldest_age_seconds: float | None = None
        if oldest_value:
            try:
                oldest_age_seconds = max((now_dt - _parse_iso(oldest_value)).total_seconds(), 0)
            except ValueError:
                oldest_age_seconds = None
        total_jobs = int(rates["total_jobs"] or 0) if rates else 0
        terminal_jobs = int(rates["terminal_jobs"] or 0) if rates else 0
        failed_jobs = int(rates["failed_jobs"] or 0) if rates else 0
        retried_jobs = int(rates["retried_jobs"] or 0) if rates else 0
        expired_leases = int(rates["expired_leases"] or 0) if rates else 0
        missing_count = int(missing["count"]) if missing else 0
        return {
            "as_of": now,
            "jobs": {str(row["status"]): int(row["count"]) for row in counts},
            "oldest_pending_at": oldest_value,
            "oldest_pending_age_seconds": oldest_age_seconds,
            "average_success_latency_ms": float(rates["average_success_latency_ms"] or 0) if rates else 0,
            "retry_rate": retried_jobs / total_jobs if total_jobs else 0,
            "terminal_failure_rate": failed_jobs / terminal_jobs if terminal_jobs else 0,
            "expired_running_leases": expired_leases,
            "generated_lessons_without_audio_or_active_job": missing_count,
            "lesson_artifacts": {str(row["scope"]): int(row["count"]) for row in artifact_counts},
            "lesson_generation_jobs": {
                str(row["status"]): int(row["count"]) for row in generation_jobs
            },
            "artifact_audio_jobs": {
                str(row["status"]): int(row["count"]) for row in artifact_jobs
            },
            "artifact_audio_files": int(artifact_audio["count"] or 0),
            "artifact_audio_bytes": int(artifact_audio["bytes"] or 0),
            "alerts": {
                "old_pending_jobs": oldest_age_seconds is not None and oldest_age_seconds > 900,
                "expired_running_leases": expired_leases > 0,
                "sustained_terminal_failures": terminal_jobs >= 10 and failed_jobs / terminal_jobs > 0.25,
                "unrecoverable_generated_lessons": missing_count > 0,
            },
        }

    def list_missing_lesson_audio_candidates(self, *, active_since: str, limit: int) -> list[tuple[int, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sessions.user_id, sessions.lesson_id
                FROM lesson_sessions AS sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.generated_lesson_json IS NOT NULL
                  AND sessions.deleted_at IS NULL
                  AND users.last_seen_at >= ?
                  AND NOT EXISTS (SELECT 1 FROM lesson_audio_cache AS cache
                                  WHERE cache.user_id = sessions.user_id AND cache.lesson_id = sessions.lesson_id)
                  AND NOT EXISTS (SELECT 1 FROM lesson_audio_jobs AS jobs
                                  WHERE jobs.user_id = sessions.user_id AND jobs.lesson_id = sessions.lesson_id
                                    AND jobs.status IN ('pending', 'running'))
                ORDER BY users.last_seen_at DESC, sessions.server_updated_at DESC
                LIMIT ?
                """,
                (active_since, max(limit, 0)),
            ).fetchall()
        return [(int(row["user_id"]), str(row["lesson_id"])) for row in rows]

    @staticmethod
    def _lesson_audio_job_from_row(row: sqlite3.Row) -> LessonAudioJob:
        return LessonAudioJob(
            id=int(row["id"]), user_id=int(row["user_id"]), lesson_id=str(row["lesson_id"]),
            content_hash=str(row["content_hash"]), status=str(row["status"]), attempt_count=int(row["attempt_count"]),
            next_attempt_at=str(row["next_attempt_at"]), lease_expires_at=str(row["lease_expires_at"]) if row["lease_expires_at"] else None,
            provider=str(row["provider"]), model=str(row["model"]), voice_config_version=str(row["voice_config_version"]),
            last_error_code=str(row["last_error_code"]) if row["last_error_code"] else None,
            last_error_summary=str(row["last_error_summary"]) if row["last_error_summary"] else None,
            created_at=str(row["created_at"]), updated_at=str(row["updated_at"]),
            completed_at=str(row["completed_at"]) if row["completed_at"] else None,
        )

    def reset_lesson_session(
        self,
        *,
        user_id: int,
        lesson_id: str,
        base_server_updated_at: str | None,
    ) -> LessonSession:
        existing = self.get_lesson_session(user_id=user_id, lesson_id=lesson_id)
        if existing is not None and base_server_updated_at != existing.server_updated_at:
            raise LessonSessionConflict(existing)

        now = _now_iso()
        state = {
            "lesson_id": lesson_id,
            "phase": "notStarted",
            "current_question_id": None,
            "translation_quiz": None,
            "current_translation_index": None,
            "translation_attempts": [],
            "mistake_notes": [],
            "audio_file_name": None,
            "is_completed": False,
            "updated_at": now,
        }
        return self.upsert_lesson_session(
            user_id=user_id,
            lesson_id=lesson_id,
            state=state,
            generated_lesson=None,
            messages=[],
            chat_summary=None,
            client_updated_at=now,
            base_server_updated_at=base_server_updated_at,
            reset_generation=True,
            lesson_artifact_id=None,
            evaluation_snapshot=None,
        )

    def _upsert_lesson_progress(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: int,
        lesson_id: str,
        status: str,
        is_completed: bool,
        completed_at: str | None,
        client_updated_at: str,
        server_updated_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO lesson_progress (
                user_id,
                lesson_id,
                status,
                is_completed,
                completed_at,
                client_updated_at,
                server_updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, lesson_id)
            DO UPDATE SET
                status = excluded.status,
                is_completed = excluded.is_completed,
                completed_at = excluded.completed_at,
                client_updated_at = excluded.client_updated_at,
                server_updated_at = excluded.server_updated_at
            """,
            (
                user_id,
                lesson_id,
                status,
                int(is_completed),
                completed_at,
                client_updated_at,
                server_updated_at,
            ),
        )

    def _delete_lesson_audio(self, connection: sqlite3.Connection, *, user_id: int, lesson_id: str) -> None:
        connection.execute(
            "DELETE FROM lesson_audio_cache WHERE user_id = ? AND lesson_id = ?",
            (user_id, lesson_id),
        )

    def _supersede_lesson_audio_jobs(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: int,
        lesson_id: str,
        current_content_hash: str | None,
        now: str,
    ) -> None:
        if current_content_hash is None:
            rows = connection.execute(
                """
                SELECT id, content_hash FROM lesson_audio_jobs
                WHERE user_id = ? AND lesson_id = ? AND status IN ('pending', 'running', 'failed')
                """,
                (user_id, lesson_id),
            ).fetchall()
            connection.execute(
                """
                UPDATE lesson_audio_jobs SET status = 'superseded', lease_expires_at = NULL,
                    updated_at = ?, completed_at = ?
                WHERE user_id = ? AND lesson_id = ? AND status IN ('pending', 'running', 'failed')
                """,
                (now, now, user_id, lesson_id),
            )
        else:
            rows = connection.execute(
                """
                SELECT id, content_hash FROM lesson_audio_jobs
                WHERE user_id = ? AND lesson_id = ? AND content_hash != ?
                  AND status IN ('pending', 'running', 'failed')
                """,
                (user_id, lesson_id, current_content_hash),
            ).fetchall()
            connection.execute(
                """
                UPDATE lesson_audio_jobs SET status = 'superseded', lease_expires_at = NULL,
                    updated_at = ?, completed_at = ?
                WHERE user_id = ? AND lesson_id = ? AND content_hash != ?
                  AND status IN ('pending', 'running', 'failed')
                """,
                (now, now, user_id, lesson_id, current_content_hash),
            )
        for row in rows:
            logger.info(
                "lesson_audio_superseded user_id=%s lesson_id=%s content_hash=%s job_id=%s",
                user_id, lesson_id, str(row["content_hash"])[:12], int(row["id"]),
            )

    def _prune_lesson_audio_cache(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: int,
        keep_count: int,
    ) -> None:
        connection.execute(
            """
            DELETE FROM lesson_audio_cache
            WHERE user_id = ?
                AND lesson_id NOT IN (
                    SELECT lesson_id FROM lesson_sessions
                    WHERE user_id = ? AND deleted_at IS NULL AND is_completed = 0
                )
                AND lesson_id NOT IN (
                    SELECT lesson_id FROM lesson_audio_jobs
                    WHERE user_id = ? AND status IN ('pending', 'running')
                )
                AND lesson_id NOT IN (
                    SELECT lesson_id
                    FROM lesson_audio_cache
                    WHERE user_id = ?
                    ORDER BY generated_at DESC, updated_at DESC, lesson_id DESC
                    LIMIT ?
                )
            """,
            (user_id, user_id, user_id, user_id, keep_count),
        )

    def completed_lesson_ids(self, *, user_id: int) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT lesson_id FROM lesson_progress WHERE user_id = ? AND is_completed = 1",
                (user_id,),
            ).fetchall()
        return {str(row["lesson_id"]) for row in rows}

    def sync_completed_lesson_ids(self, *, user_id: int, lesson_ids: set[str]) -> int:
        if not lesson_ids:
            return len(self.completed_lesson_ids(user_id=user_id))

        now = _now_iso()
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO lesson_progress (
                    user_id,
                    lesson_id,
                    status,
                    is_completed,
                    completed_at,
                    client_updated_at,
                    server_updated_at
                )
                VALUES (?, ?, 'completed', 1, ?, ?, ?)
                ON CONFLICT(user_id, lesson_id)
                DO UPDATE SET
                    status = 'completed',
                    is_completed = 1,
                    completed_at = COALESCE(lesson_progress.completed_at, excluded.completed_at),
                    client_updated_at = excluded.client_updated_at,
                    server_updated_at = excluded.server_updated_at
                WHERE lesson_progress.is_completed = 0
                """,
                [(user_id, lesson_id, now, now, now) for lesson_id in sorted(lesson_ids)],
            )
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM lesson_progress WHERE user_id = ? AND is_completed = 1",
                (user_id,),
            ).fetchone()
            connection.commit()
        return int(row["count"])

    def learning_target_states(self, *, user_id: int, target_keys: list[str]) -> dict[str, dict[str, Any]]:
        if not target_keys:
            return {}
        placeholders = ",".join("?" for _ in target_keys)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM user_learning_targets
                WHERE user_id = ? AND target_key IN ({placeholders})
                """,
                [user_id, *target_keys],
            ).fetchall()
        return {str(row["target_key"]): self._learning_target_dict(row) for row in rows}

    def list_active_learning_targets(self, *, user_id: int, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    user_learning_targets.*,
                    (
                        SELECT outcome FROM learning_evidence_events
                        WHERE learning_target_id = user_learning_targets.id
                        ORDER BY created_at DESC
                        LIMIT 1
                    ) AS latest_evidence_outcome,
                    (
                        SELECT evidence_json FROM learning_evidence_events
                        WHERE learning_target_id = user_learning_targets.id
                        ORDER BY created_at DESC
                        LIMIT 1
                    ) AS latest_evidence_json
                FROM user_learning_targets
                WHERE user_id = ? AND status = 'active'
                ORDER BY priority_score DESC, last_evaluated_at ASC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [self._learning_target_dict(row) for row in rows]

    def create_translation_lookup_event(
        self,
        *,
        user_id: int,
        source_kind: str,
        source_id: str,
        source_surface: str | None,
        selected_text: str,
        normalized_text: str,
        surrounding_text: str | None,
        visible_course_level: str | None,
        request_created_at: str | None,
    ) -> dict[str, Any]:
        now = _now_iso()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO translation_lookup_events (
                    user_id, source_kind, source_id, source_surface, selected_text,
                    normalized_text, surrounding_text, visible_course_level,
                    request_created_at, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    user_id,
                    source_kind,
                    source_id,
                    source_surface,
                    selected_text,
                    normalized_text,
                    surrounding_text,
                    visible_course_level,
                    request_created_at,
                    now,
                ),
            )
            lookup_id = int(cursor.lastrowid)
            connection.commit()
            row = connection.execute(
                "SELECT * FROM translation_lookup_events WHERE id = ? AND user_id = ?",
                (lookup_id, user_id),
            ).fetchone()
        if row is None:
            raise RuntimeError("Translation lookup insert did not return a row.")
        return self._translation_lookup_event_dict(row)

    def enqueue_translation_lookup_evaluation(
        self,
        *,
        user_id: int,
        lookup_event_id: int,
        snapshot: dict[str, Any] | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if snapshot is None:
                connection.execute(
                    """
                    UPDATE translation_lookup_events
                    SET status = 'ignored', evaluated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (_now_iso(), lookup_event_id, user_id),
                )
            else:
                self._enqueue_evaluation_job(
                    connection,
                    user_id=user_id,
                    source_kind="translation_lookup",
                    source_id=str(snapshot["source_id"]),
                    snapshot=snapshot,
                    prompt_version="evaluator_v3",
                )
            connection.commit()

    def create_vocabulary_practice(
        self,
        *,
        user_id: int,
        progression: dict[str, Any],
        selected_targets: list[dict[str, Any]],
        model: str,
        prompt_version: str,
    ) -> VocabularyPracticeSession:
        now = _now_iso()
        practice_id = str(uuid.uuid4())
        selection = {
            "progression": progression,
            "targets": selected_targets,
            "generation": {
                "model": model,
                "prompt_version": prompt_version,
            },
        }
        state = {
            "current_question_index": 0,
            "answered_question_ids": [],
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO vocabulary_practice_sessions (
                    id, user_id, course_level, stage_number, progress_cutoff_absolute_day,
                    status, selection_snapshot_json, quiz_json, state_json, messages_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'generating', ?, NULL, ?, '[]', ?, ?)
                """,
                (
                    practice_id,
                    user_id,
                    progression["course_level"],
                    int(progression["stage_number"]),
                    int(progression["progress_cutoff_absolute_day"]),
                    _dump_json(selection),
                    _dump_json(state),
                    now,
                    now,
                ),
            )
            connection.commit()
        practice = self.get_vocabulary_practice(user_id=user_id, practice_id=practice_id)
        if practice is None:
            raise RuntimeError("Vocabulary practice insert did not return a row.")
        return practice

    def activate_vocabulary_practice(
        self,
        *,
        user_id: int,
        practice_id: str,
        quiz: dict[str, Any],
    ) -> VocabularyPracticeSession:
        now = _now_iso()
        opening = str(quiz.get("opening_text") or "Översätt meningarna till svenska.")
        first_sentence = str(quiz["questions"][0]["sentence_en"])
        messages = [
            _practice_message("assistant", opening, now),
            _practice_message("assistant", f"Översätt 1/5: **{first_sentence}**", now),
        ]
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE vocabulary_practice_sessions
                SET status = 'active', quiz_json = ?, messages_json = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND status = 'generating'
                """,
                (_dump_json(quiz), _dump_json(messages), now, practice_id, user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Vocabulary practice is not generating.")
            connection.commit()
        practice = self.get_vocabulary_practice(user_id=user_id, practice_id=practice_id)
        if practice is None:
            raise RuntimeError("Vocabulary practice activation did not return a row.")
        return practice

    def fail_vocabulary_practice(self, *, user_id: int, practice_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE vocabulary_practice_sessions
                SET status = 'failed', updated_at = ?
                WHERE id = ? AND user_id = ? AND status = 'generating'
                """,
                (_now_iso(), practice_id, user_id),
            )
            connection.commit()

    def list_vocabulary_practices(self, *, user_id: int, limit: int = 100) -> list[VocabularyPracticeSession]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM vocabulary_practice_sessions
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [self._vocabulary_practice_from_row(row) for row in rows]

    def get_vocabulary_practice(
        self,
        *,
        user_id: int,
        practice_id: str,
    ) -> VocabularyPracticeSession | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM vocabulary_practice_sessions WHERE id = ? AND user_id = ?",
                (practice_id, user_id),
            ).fetchone()
        return self._vocabulary_practice_from_row(row) if row is not None else None

    def append_vocabulary_interaction(
        self,
        *,
        user_id: int,
        practice_id: str,
        user_text: str,
        assistant_response: dict[str, Any],
    ) -> VocabularyPracticeSession:
        now = _now_iso()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM vocabulary_practice_sessions WHERE id = ? AND user_id = ?",
                (practice_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError("Vocabulary practice not found.")
            practice = self._vocabulary_practice_from_row(row)
            if practice.status != "active" or practice.quiz is None:
                raise ValueError("Vocabulary practice is not active.")

            messages = list(practice.messages)
            messages.append(_practice_message("user", user_text, now))
            assistant_message = _practice_message("assistant", str(assistant_response["assistant_text"]), now)
            assistant_message["turn_kind"] = assistant_response.get("turn_kind")
            assistant_message["answer_assessment"] = assistant_response.get("answer_assessment")
            assistant_message["active_question_answered"] = bool(
                assistant_response.get("active_question_answered")
            )
            messages.append(assistant_message)
            state = dict(practice.state)
            index = int(state.get("current_question_index", 0))
            questions = practice.quiz.get("questions") or []
            if bool(assistant_response.get("active_question_answered")) and 0 <= index < len(questions):
                answered = list(state.get("answered_question_ids") or [])
                question_id = str(questions[index]["id"])
                if question_id not in answered:
                    answered.append(question_id)
                state["answered_question_ids"] = answered

            connection.execute(
                """
                UPDATE vocabulary_practice_sessions
                SET state_json = ?, messages_json = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (_dump_json(state), _dump_json(messages), now, practice_id, user_id),
            )
            connection.commit()
        updated = self.get_vocabulary_practice(user_id=user_id, practice_id=practice_id)
        if updated is None:
            raise RuntimeError("Vocabulary interaction update did not return a row.")
        return updated

    def advance_vocabulary_practice(
        self,
        *,
        user_id: int,
        practice_id: str,
    ) -> VocabularyPracticeSession:
        now = _now_iso()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM vocabulary_practice_sessions WHERE id = ? AND user_id = ?",
                (practice_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError("Vocabulary practice not found.")
            practice = self._vocabulary_practice_from_row(row)
            if practice.status != "active" or practice.quiz is None:
                raise ValueError("Vocabulary practice is not active.")

            state = dict(practice.state)
            questions = practice.quiz.get("questions") or []
            index = int(state.get("current_question_index", 0))
            if not 0 <= index < len(questions):
                raise ValueError("Vocabulary practice has invalid question state.")
            question_id = str(questions[index]["id"])
            if question_id not in set(state.get("answered_question_ids") or []):
                raise ValueError("Answer the active question before continuing.")

            messages = list(practice.messages)
            if index + 1 < len(questions):
                next_index = index + 1
                state["current_question_index"] = next_index
                sentence = str(questions[next_index]["sentence_en"])
                messages.append(
                    _practice_message(
                        "assistant",
                        f"Översätt {next_index + 1}/{len(questions)}: **{sentence}**",
                        now,
                    )
                )
                connection.execute(
                    """
                    UPDATE vocabulary_practice_sessions
                    SET state_json = ?, messages_json = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (_dump_json(state), _dump_json(messages), now, practice_id, user_id),
                )
            else:
                messages.append(_practice_message("assistant", "Klart. Övningen är färdig.", now))
                state["completed"] = True
                connection.execute(
                    """
                    UPDATE vocabulary_practice_sessions
                    SET status = 'completed', state_json = ?, messages_json = ?,
                        updated_at = ?, completed_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (_dump_json(state), _dump_json(messages), now, now, practice_id, user_id),
                )
                snapshot = {
                    "evaluation_version": "v3",
                    "source_kind": "vocabulary_practice",
                    "source_id": practice_id,
                    "progression": practice.selection_snapshot.get("progression") or {},
                    "candidates": practice.selection_snapshot.get("targets") or [],
                    "quiz": practice.quiz,
                    "turns": _evaluation_turns(messages),
                    "has_meaningful_evidence": True,
                }
                self._enqueue_evaluation_job(
                    connection,
                    user_id=user_id,
                    source_kind="vocabulary_practice",
                    source_id=practice_id,
                    snapshot=snapshot,
                    prompt_version="evaluator_v3",
                )
            connection.commit()
        updated = self.get_vocabulary_practice(user_id=user_id, practice_id=practice_id)
        if updated is None:
            raise RuntimeError("Vocabulary practice advance did not return a row.")
        return updated

    def abandon_vocabulary_practice(self, *, user_id: int, practice_id: str) -> VocabularyPracticeSession:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM vocabulary_practice_sessions WHERE id = ? AND user_id = ?",
                (practice_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError("Vocabulary practice not found.")
            practice = self._vocabulary_practice_from_row(row)
            if practice.status not in {"generating", "active"}:
                raise ValueError("Vocabulary practice cannot be ended.")
            connection.execute(
                """
                UPDATE vocabulary_practice_sessions
                SET status = 'abandoned', updated_at = ?
                WHERE id = ? AND user_id = ? AND status IN ('generating', 'active')
                """,
                (_now_iso(), practice_id, user_id),
            )
            questions = (practice.quiz or {}).get("questions") or []
            answered = set(practice.state.get("answered_question_ids") or [])
            if questions and all(str(question.get("id")) in answered for question in questions):
                snapshot = {
                    "evaluation_version": "v3",
                    "source_kind": "vocabulary_practice",
                    "source_id": practice_id,
                    "progression": practice.selection_snapshot.get("progression") or {},
                    "candidates": practice.selection_snapshot.get("targets") or [],
                    "quiz": practice.quiz,
                    "turns": _evaluation_turns(practice.messages),
                    "has_meaningful_evidence": True,
                }
                self._enqueue_evaluation_job(
                    connection,
                    user_id=user_id,
                    source_kind="vocabulary_practice",
                    source_id=practice_id,
                    snapshot=snapshot,
                    prompt_version="evaluator_v3",
                )
            connection.commit()
        practice = self.get_vocabulary_practice(user_id=user_id, practice_id=practice_id)
        if practice is None:
            raise RuntimeError("Vocabulary practice abandon did not return a row.")
        return practice

    def claim_evaluation_job(self, *, lease_seconds: int = 300) -> EvaluationJob | None:
        now = _now_iso()
        lease = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat(timespec="microseconds").replace("+00:00", "Z")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM evaluation_jobs
                WHERE (
                    status = 'pending' AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ) OR (
                    status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?
                )
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (now, now),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE evaluation_jobs
                SET status = 'running', attempt_count = attempt_count + 1,
                    lease_expires_at = ?, last_error = NULL
                WHERE id = ?
                """,
                (lease, int(row["id"])),
            )
            connection.commit()
            return EvaluationJob(
                id=int(row["id"]),
                user_id=int(row["user_id"]),
                source_kind=str(row["source_kind"]),
                source_id=str(row["source_id"]),
                input_snapshot=json.loads(row["input_snapshot_json"]),
                attempt_count=int(row["attempt_count"]) + 1,
                prompt_version=str(row["prompt_version"]),
            )

    def apply_evaluation_results(
        self,
        *,
        job: EvaluationJob,
        model: str,
        raw_output: dict[str, Any],
        results: list[dict[str, Any]],
    ) -> None:
        now = _now_iso()
        candidates = {
            str(candidate["target_key"]): candidate
            for candidate in job.input_snapshot.get("candidates", [])
            if isinstance(candidate, dict) and candidate.get("target_key")
        }
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for result in results:
                if result.get("outcome") == "no_evidence":
                    continue
                key = str(result["target_key"])
                candidate = candidates[key]
                target_row = connection.execute(
                    """
                    SELECT * FROM user_learning_targets
                    WHERE user_id = ? AND target_kind = ? AND target_key = ?
                    """,
                        (job.user_id, candidate["target_kind"], key),
                ).fetchone()
                outcome = str(result["outcome"])
                if target_row is None and outcome == "demonstrated":
                    continue
                if target_row is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO user_learning_targets (
                            user_id, target_kind, target_key, display_text, target_subtype,
                            status, priority_score, success_streak, struggle_count,
                            evidence_count, source_level, first_seen_at, last_evaluated_at
                        ) VALUES (?, ?, ?, ?, ?, 'active', ?, 0, ?, 0, ?, ?, ?)
                        """,
                        (
                            job.user_id,
                            candidate["target_kind"],
                            key,
                            candidate["display_text"],
                            candidate["target_subtype"],
                            0.0,
                            0,
                            candidate["source_level"],
                            now,
                            now,
                        ),
                    )
                    target_id = int(cursor.lastrowid)
                    target_row = connection.execute(
                        "SELECT * FROM user_learning_targets WHERE id = ?",
                        (target_id,),
                    ).fetchone()
                target_id = int(target_row["id"])

                if outcome == "lookup_requested":
                    previous_lookup_count = connection.execute(
                        """
                        SELECT COUNT(*) AS count FROM learning_evidence_events
                        WHERE learning_target_id = ? AND outcome = 'lookup_requested'
                        """,
                        (target_id,),
                    ).fetchone()
                    lookup_count = int(previous_lookup_count["count"]) if previous_lookup_count else 0
                    priority = min(
                        100.0,
                        float(target_row["priority_score"]) + float(candidate.get("lookup_priority_delta", 1.0)),
                    )
                    was_resolved = str(target_row["status"]) == "resolved"
                    reactivate = not was_resolved or priority >= 6.0 or lookup_count > 0
                    connection.execute(
                        """
                        UPDATE user_learning_targets
                        SET status = ?, priority_score = ?,
                            evidence_count = evidence_count + 1,
                            last_evaluated_at = ?, resolved_at = ?
                        WHERE id = ?
                        """,
                        (
                            "active" if reactivate else "resolved",
                            priority,
                            now,
                            None if reactivate else target_row["resolved_at"],
                            target_id,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO learning_evidence_events (
                            user_id, learning_target_id, evaluation_job_id, source_kind, source_id,
                            outcome, evidence_strength, confidence, evidence_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            job.user_id,
                            target_id,
                            job.id,
                            job.source_kind,
                            job.source_id,
                            outcome,
                            result["evidence_strength"],
                            float(result["confidence"]),
                            _dump_json(
                                {
                                    "evidence_lookup_ids": result.get("evidence_lookup_ids") or [],
                                    "reason": str(result.get("reason") or "")[:500],
                                    "priority_reason": candidate.get("priority_reason"),
                                    "lookup_context": candidate.get("lookup_context"),
                                    "lookup_priority_delta": candidate.get("lookup_priority_delta"),
                                }
                            ),
                            now,
                        ),
                    )
                    continue

                qualifies = (
                    outcome == "demonstrated"
                    and str(result["evidence_strength"]) == "production"
                    and float(result["confidence"]) >= 0.8
                )
                success_streak = int(target_row["success_streak"])
                if qualifies:
                    previous = connection.execute(
                        """
                        SELECT source_kind, source_id FROM learning_evidence_events
                        WHERE learning_target_id = ? AND outcome = 'demonstrated'
                          AND evidence_strength = 'production' AND confidence >= 0.8
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        (target_id,),
                    ).fetchone()
                    if previous is None or (
                        str(previous["source_kind"]), str(previous["source_id"])
                    ) != (job.source_kind, job.source_id):
                        success_streak += 1
                elif outcome in {"struggled", "partial"}:
                    success_streak = 0

                priority = float(target_row["priority_score"])
                if outcome == "struggled":
                    priority = min(100.0, priority + 3.0)
                elif outcome == "partial":
                    priority = min(100.0, priority + 1.5)
                elif qualifies:
                    priority = max(0.0, priority - 2.0)
                resolved = success_streak >= 2
                status_value = "resolved" if resolved else "active"
                if outcome in {"struggled", "partial"}:
                    status_value = "active"
                    resolved = False
                connection.execute(
                    """
                    UPDATE user_learning_targets
                    SET status = ?, priority_score = ?, success_streak = ?,
                        struggle_count = struggle_count + ?, evidence_count = evidence_count + 1,
                        last_evaluated_at = ?, resolved_at = ?
                    WHERE id = ?
                    """,
                    (
                        status_value,
                        priority,
                        success_streak,
                        1 if outcome == "struggled" else 0,
                        now,
                        now if resolved else None,
                        target_id,
                    ),
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO learning_evidence_events (
                        user_id, learning_target_id, evaluation_job_id, source_kind, source_id,
                        outcome, evidence_strength, confidence, evidence_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job.user_id,
                        target_id,
                        job.id,
                        job.source_kind,
                        job.source_id,
                        outcome,
                        result["evidence_strength"],
                        float(result["confidence"]),
                        _dump_json(
                            {
                                "evidence_turn_ids": result.get("evidence_turn_ids") or [],
                                "reason": str(result.get("reason") or "")[:500],
                            }
                        ),
                        now,
                    ),
                )
            connection.execute(
                """
                UPDATE evaluation_jobs
                SET status = 'succeeded', model = ?, raw_output_json = ?,
                    completed_at = ?, lease_expires_at = NULL, next_attempt_at = NULL
                WHERE id = ?
                """,
                (model, _dump_json(raw_output), now, job.id),
            )
            self._mark_translation_lookup_events(
                connection,
                snapshot=job.input_snapshot,
                status="evaluated",
                completed_at=now,
                error=None,
            )
            connection.commit()

    def fail_evaluation_job(self, *, job: EvaluationJob, error: str, max_attempts: int = 5) -> None:
        now_dt = datetime.now(UTC)
        terminal = job.attempt_count >= max_attempts
        next_attempt = now_dt + timedelta(seconds=min(300, 2 ** job.attempt_count))
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE evaluation_jobs
                SET status = ?, last_error = ?, next_attempt_at = ?,
                    lease_expires_at = NULL, completed_at = ?
                WHERE id = ?
                """,
                (
                    "failed" if terminal else "pending",
                    error[:1000],
                    None if terminal else next_attempt.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                    _now_iso() if terminal else None,
                    job.id,
                ),
            )
            if terminal:
                self._mark_translation_lookup_events(
                    connection,
                    snapshot=job.input_snapshot,
                    status="failed",
                    completed_at=_now_iso(),
                    error=error,
                )
            connection.commit()

    def _mark_translation_lookup_events(
        self,
        connection: sqlite3.Connection,
        *,
        snapshot: dict[str, Any],
        status: str,
        completed_at: str,
        error: str | None,
    ) -> None:
        if snapshot.get("source_kind") != "translation_lookup":
            return
        lookup_ids: list[int] = []
        for lookup in snapshot.get("lookup_events", []):
            if not isinstance(lookup, dict):
                continue
            value = str(lookup.get("lookup_id") or "")
            if not value.startswith("lookup_"):
                continue
            try:
                lookup_ids.append(int(value.removeprefix("lookup_")))
            except ValueError:
                continue
        for lookup_id in lookup_ids:
            connection.execute(
                """
                UPDATE translation_lookup_events
                SET status = ?, evaluated_at = ?, last_error = ?
                WHERE id = ?
                """,
                (status, completed_at, error[:1000] if error else None, lookup_id),
            )

    def _enqueue_evaluation_job(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: int,
        source_kind: str,
        source_id: str,
        snapshot: dict[str, Any],
        prompt_version: str,
    ) -> None:
        target_keys = [
            str(candidate["target_key"])
            for candidate in snapshot.get("candidates", [])
            if isinstance(candidate, dict) and candidate.get("target_key")
        ]
        current_state: dict[str, dict[str, Any]] = {}
        if target_keys:
            placeholders = ",".join("?" for _ in target_keys)
            rows = connection.execute(
                f"SELECT * FROM user_learning_targets WHERE user_id = ? AND target_key IN ({placeholders})",
                [user_id, *target_keys],
            ).fetchall()
            current_state = {str(row["target_key"]): self._learning_target_dict(row) for row in rows}
        final_snapshot = dict(snapshot)
        final_snapshot["current_user_state"] = current_state
        serialized = _dump_json(final_snapshot)
        input_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        meaningful = bool(final_snapshot.get("has_meaningful_evidence"))
        connection.execute(
            """
            INSERT OR IGNORE INTO evaluation_jobs (
                user_id, source_kind, source_id, input_hash, input_snapshot_json,
                status, prompt_version, created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                source_kind,
                source_id,
                input_hash,
                serialized,
                "pending" if meaningful else "skipped_no_evidence",
                prompt_version,
                _now_iso(),
                None if meaningful else _now_iso(),
            ),
        )

    @staticmethod
    def _learning_target_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = {
            "id": int(row["id"]),
            "target_kind": str(row["target_kind"]),
            "target_key": str(row["target_key"]),
            "display_text": str(row["display_text"]),
            "target_subtype": str(row["target_subtype"]),
            "status": str(row["status"]),
            "priority_score": float(row["priority_score"]),
            "success_streak": int(row["success_streak"]),
            "struggle_count": int(row["struggle_count"]),
            "evidence_count": int(row["evidence_count"]),
            "source_level": str(row["source_level"]),
            "last_evaluated_at": str(row["last_evaluated_at"]),
            "resolved_at": row["resolved_at"],
        }
        keys = set(row.keys())
        if "latest_evidence_outcome" in keys and row["latest_evidence_outcome"]:
            result["latest_evidence_outcome"] = str(row["latest_evidence_outcome"])
        if "latest_evidence_json" in keys and row["latest_evidence_json"]:
            try:
                result["latest_evidence_json"] = json.loads(row["latest_evidence_json"])
            except json.JSONDecodeError:
                result["latest_evidence_json"] = {}
        return result

    @staticmethod
    def _translation_lookup_event_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "user_id": int(row["user_id"]),
            "source_kind": str(row["source_kind"]),
            "source_id": str(row["source_id"]),
            "source_surface": row["source_surface"],
            "selected_text": str(row["selected_text"]),
            "normalized_text": str(row["normalized_text"]),
            "surrounding_text": row["surrounding_text"],
            "visible_course_level": row["visible_course_level"],
            "request_created_at": row["request_created_at"],
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "evaluated_at": row["evaluated_at"],
            "last_error": row["last_error"],
        }

    @staticmethod
    def _vocabulary_practice_from_row(row: sqlite3.Row) -> VocabularyPracticeSession:
        return VocabularyPracticeSession(
            id=str(row["id"]),
            course_level=str(row["course_level"]),
            stage_number=int(row["stage_number"]),
            progress_cutoff_absolute_day=int(row["progress_cutoff_absolute_day"]),
            status=str(row["status"]),
            selection_snapshot=json.loads(row["selection_snapshot_json"]),
            quiz=json.loads(row["quiz_json"]) if row["quiz_json"] else None,
            state=json.loads(row["state_json"]),
            messages=json.loads(row["messages_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            completed_at=row["completed_at"],
        )

    def _lesson_session_from_row(self, row: sqlite3.Row) -> LessonSession:
        return LessonSession(
            lesson_id=row["lesson_id"],
            state=json.loads(row["state_json"]),
            generated_lesson=json.loads(row["generated_lesson_json"]) if row["generated_lesson_json"] else None,
            messages=json.loads(row["messages_json"] or "[]"),
            chat_summary=json.loads(row["chat_summary_json"]) if row["chat_summary_json"] else None,
            status=row["status"],
            is_completed=bool(row["is_completed"]),
            completed_at=row["completed_at"],
            client_updated_at=row["client_updated_at"],
            server_updated_at=row["server_updated_at"],
            state_schema_version=int(row["state_schema_version"]),
            content_schema_version=int(row["content_schema_version"]),
            has_audio=_row_bool(row, "has_audio"),
            lesson_artifact_id=(
                str(row["lesson_artifact_id"])
                if "lesson_artifact_id" in row.keys() and row["lesson_artifact_id"] is not None
                else None
            ),
        )

    @staticmethod
    def _lesson_artifact_from_row(row: sqlite3.Row) -> LessonArtifact:
        return LessonArtifact(
            id=str(row["id"]),
            lesson_id=str(row["lesson_id"]),
            scope=str(row["scope"]),
            owner_user_id=int(row["owner_user_id"]) if row["owner_user_id"] is not None else None,
            recipe_fingerprint=str(row["recipe_fingerprint"]),
            recipe=json.loads(str(row["recipe_json"])),
            lesson_content_hash=str(row["lesson_content_hash"]),
            generated_lesson=json.loads(str(row["generated_lesson_json"])),
            requested_model=str(row["requested_model"]),
            provider_model=str(row["provider_model"]) if row["provider_model"] is not None else None,
            reasoning_effort=str(row["reasoning_effort"]),
            provider_request_id=(
                str(row["provider_request_id"]) if row["provider_request_id"] is not None else None
            ),
            created_by_user_id=int(row["created_by_user_id"]),
            created_at=str(row["created_at"]),
            invalidated_at=str(row["invalidated_at"]) if row["invalidated_at"] is not None else None,
        )

    @staticmethod
    def _lesson_generation_job_from_row(row: sqlite3.Row) -> LessonGenerationJob:
        return LessonGenerationJob(
            id=int(row["id"]), lesson_id=str(row["lesson_id"]),
            recipe_fingerprint=str(row["recipe_fingerprint"]), recipe=json.loads(str(row["recipe_json"])),
            scope=str(row["scope"]),
            owner_user_id=int(row["owner_user_id"]) if row["owner_user_id"] is not None else None,
            requested_by_user_id=int(row["requested_by_user_id"]), status=str(row["status"]),
            attempt_count=int(row["attempt_count"]),
            lease_expires_at=str(row["lease_expires_at"]) if row["lease_expires_at"] is not None else None,
            artifact_id=str(row["artifact_id"]) if row["artifact_id"] is not None else None,
            last_error_code=str(row["last_error_code"]) if row["last_error_code"] is not None else None,
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _artifact_audio_from_row(row: sqlite3.Row) -> ArtifactAudio:
        return ArtifactAudio(
            lesson_artifact_id=str(row["lesson_artifact_id"]), content_hash=str(row["content_hash"]),
            audio_recipe_fingerprint=str(row["audio_recipe_fingerprint"]),
            relative_file_path=str(row["relative_file_path"]), content_type=str(row["content_type"]),
            byte_count=int(row["byte_count"]), model=str(row["model"]),
            voice_config_version=str(row["voice_config_version"]), updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _artifact_audio_job_from_row(row: sqlite3.Row) -> ArtifactAudioJob:
        return ArtifactAudioJob(
            id=int(row["id"]), lesson_artifact_id=str(row["lesson_artifact_id"]),
            requested_by_user_id=int(row["requested_by_user_id"]), lesson_id=str(row["lesson_id"]),
            content_hash=str(row["content_hash"]), dialogue_text_hash=str(row["dialogue_text_hash"]),
            audio_recipe_fingerprint=str(row["audio_recipe_fingerprint"]), status=str(row["status"]),
            attempt_count=int(row["attempt_count"]), next_attempt_at=str(row["next_attempt_at"]),
            lease_expires_at=str(row["lease_expires_at"]) if row["lease_expires_at"] is not None else None,
            model=str(row["model"]), voice_config_version=str(row["voice_config_version"]),
            last_error_code=str(row["last_error_code"]) if row["last_error_code"] is not None else None,
            updated_at=str(row["updated_at"]),
        )


def _progress_row_as_completed_session(row: sqlite3.Row) -> LessonSession:
    timestamp = str(row["client_updated_at"] or row["server_updated_at"])
    lesson_id = str(row["lesson_id"])
    return LessonSession(
        lesson_id=lesson_id,
        state={
            "lesson_id": lesson_id,
            "phase": "completed",
            "current_question_id": None,
            "translation_quiz": None,
            "current_translation_index": None,
            "translation_attempts": [],
            "mistake_notes": [],
            "audio_file_name": None,
            "is_completed": True,
            "updated_at": timestamp,
        },
        generated_lesson=None,
        messages=[],
        chat_summary=None,
        status="completed",
        is_completed=True,
        completed_at=row["completed_at"],
        client_updated_at=timestamp,
        server_updated_at=str(row["server_updated_at"]),
        state_schema_version=1,
        content_schema_version=1,
        has_audio=_row_bool(row, "has_audio"),
        lesson_artifact_id=None,
    )


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row_bool(row: sqlite3.Row, key: str) -> bool:
    return key in row.keys() and bool(row[key])


def _usage_row_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    decoded: dict[str, Any] = {}
    for key in row.keys():
        value = row[key]
        if key.endswith("_tokens") or key in {"request_count", "user_id", "elapsed_ms"}:
            decoded[key] = int(value or 0)
        elif key.endswith("_cost_usd") or key.endswith("_ratio"):
            decoded[key] = float(value or 0.0)
        else:
            decoded[key] = value
    return decoded


def _practice_message(role: str, content: str, created_at: str) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "role": role,
        "content": content,
        "created_at": created_at,
    }


def _evaluation_turns(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "turn_id": f"turn_{index}",
            "role": str(message.get("role") or ""),
            "content": str(message.get("content") or "")[:4000],
            "turn_kind": message.get("turn_kind"),
            "answer_assessment": message.get("answer_assessment"),
            "active_question_answered": message.get("active_question_answered"),
        }
        for index, message in enumerate(messages[-200:], start=1)
        if message.get("role") in {"user", "assistant"}
    ]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _generated_lesson_hash(generated_lesson: dict[str, Any] | None) -> str | None:
    if generated_lesson is None:
        return None
    try:
        return lesson_audio_content_hash(generated_lesson)
    except ValueError:
        return None


def _status_from_state(state: dict[str, Any]) -> str:
    phase = str(state.get("phase") or "notStarted")
    statuses = {
        "notStarted": "not_started",
        "not_started": "not_started",
        "generated": "generated",
        "listening": "listening",
        "comprehension": "comprehension",
        "discussion": "discussion",
        "translation": "translation",
        "completed": "completed",
    }
    return statuses.get(phase, phase)


def _completed_at(
    existing: LessonSession | None,
    is_completed: bool,
    state: dict[str, Any],
    fallback: str,
) -> str | None:
    if not is_completed:
        return None
    if existing and existing.completed_at:
        return existing.completed_at
    value = state.get("completed_at")
    return str(value) if value else fallback
