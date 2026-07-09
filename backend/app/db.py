from __future__ import annotations

import json
import hashlib
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


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


@dataclass(frozen=True)
class LessonAudio:
    lesson_id: str
    audio_data: bytes
    content_type: str
    byte_count: int
    completed_at: str
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
            connection.execute(
                """
                UPDATE vocabulary_practice_sessions
                SET status = 'failed', updated_at = ?
                WHERE status = 'generating'
                """,
                (_now_iso(),),
            )
            connection.commit()

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

    def record_openai_usage(self, event: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO openai_usage_events (
                    user_id, request_role, request_name, source_id, model, prompt_version,
                    prompt_cache_key, input_tokens, cached_tokens, output_tokens,
                    reasoning_tokens, total_tokens, estimated_cost_usd, actual_cost_usd,
                    elapsed_ms, openai_request_id, created_at, raw_usage_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    event.get("output_tokens"),
                    event.get("reasoning_tokens"),
                    event.get("total_tokens"),
                    event.get("estimated_cost_usd"),
                    event.get("actual_cost_usd"),
                    int(event.get("elapsed_ms") or 0),
                    event.get("openai_request_id"),
                    event.get("created_at") or _now_iso(),
                    _dump_json(event.get("raw_usage") or {}),
                ),
            )
            connection.commit()

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
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0.0) AS estimated_cost_usd,
                    COALESCE(SUM(actual_cost_usd), 0.0) AS actual_cost_usd
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
                    COALESCE(SUM(openai_usage_events.output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(openai_usage_events.reasoning_tokens), 0) AS reasoning_tokens,
                    COALESCE(SUM(openai_usage_events.total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(openai_usage_events.estimated_cost_usd), 0.0) AS estimated_cost_usd,
                    COALESCE(SUM(openai_usage_events.actual_cost_usd), 0.0) AS actual_cost_usd
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
                    COALESCE(SUM(openai_usage_events.output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(openai_usage_events.reasoning_tokens), 0) AS reasoning_tokens,
                    COALESCE(SUM(openai_usage_events.total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(openai_usage_events.estimated_cost_usd), 0.0) AS estimated_cost_usd,
                    COALESCE(SUM(openai_usage_events.actual_cost_usd), 0.0) AS actual_cost_usd
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
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0.0) AS estimated_cost_usd,
                    COALESCE(SUM(actual_cost_usd), 0.0) AS actual_cost_usd
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
                    openai_usage_events.output_tokens,
                    openai_usage_events.reasoning_tokens,
                    openai_usage_events.total_tokens,
                    openai_usage_events.estimated_cost_usd,
                    openai_usage_events.actual_cost_usd,
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
                EXISTS (
                    SELECT 1
                    FROM lesson_audio_cache
                    WHERE lesson_audio_cache.user_id = lesson_sessions.user_id
                        AND lesson_audio_cache.lesson_id = lesson_sessions.lesson_id
                ) AS has_audio
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

    def get_lesson_session(self, *, user_id: int, lesson_id: str) -> LessonSession | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT lesson_sessions.*,
                    EXISTS (
                        SELECT 1
                        FROM lesson_audio_cache
                        WHERE lesson_audio_cache.user_id = lesson_sessions.user_id
                            AND lesson_audio_cache.lesson_id = lesson_sessions.lesson_id
                    ) AS has_audio
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
                        messages_json,
                        chat_summary_json,
                        status,
                        is_completed,
                        completed_at,
                        client_updated_at,
                        server_updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        lesson_id,
                        state_json,
                        generated_lesson_json,
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
            if not is_completed:
                self._delete_lesson_audio(connection, user_id=user_id, lesson_id=lesson_id)
            existing_completed = existing is not None and (existing.is_completed or existing.status == "completed")
            if is_completed and not existing_completed and evaluation_snapshot is not None:
                self._enqueue_evaluation_job(
                    connection,
                    user_id=user_id,
                    source_kind="lesson",
                    source_id=lesson_id,
                    snapshot=evaluation_snapshot,
                    prompt_version="evaluator_v2",
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
    ) -> LessonAudio | None:
        now = _now_iso()
        with self._connect() as connection:
            progress = connection.execute(
                """
                SELECT completed_at, server_updated_at
                FROM lesson_progress
                WHERE user_id = ? AND lesson_id = ? AND is_completed = 1
                """,
                (user_id, lesson_id),
            ).fetchone()
            if progress is None:
                return None

            completed_at = str(progress["completed_at"] or progress["server_updated_at"] or now)
            connection.execute(
                """
                INSERT INTO lesson_audio_cache (
                    user_id,
                    lesson_id,
                    audio_data,
                    content_type,
                    byte_count,
                    completed_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, lesson_id)
                DO UPDATE SET
                    audio_data = excluded.audio_data,
                    content_type = excluded.content_type,
                    byte_count = excluded.byte_count,
                    completed_at = excluded.completed_at,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    lesson_id,
                    audio_data,
                    content_type,
                    len(audio_data),
                    completed_at,
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
                SELECT lesson_id, audio_data, content_type, byte_count, completed_at, updated_at
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
            completed_at=str(row["completed_at"]),
            updated_at=str(row["updated_at"]),
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
                    SELECT lesson_id
                    FROM lesson_audio_cache
                    WHERE user_id = ?
                    ORDER BY completed_at DESC, updated_at DESC, lesson_id DESC
                    LIMIT ?
                )
            """,
            (user_id, user_id, keep_count),
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
                    prompt_version="evaluator_v2",
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
                    "evaluation_version": "v1",
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
                    prompt_version="evaluator_v2",
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
                    "evaluation_version": "v1",
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
                    prompt_version="evaluator_v2",
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
        elif key.endswith("_cost_usd"):
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
