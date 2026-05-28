from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
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


class LessonSessionConflict(Exception):
    def __init__(self, current: LessonSession) -> None:
        super().__init__("Lesson session conflict.")
        self.current = current


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

    def list_lesson_sessions(
        self,
        *,
        user_id: int,
        updated_after: str | None = None,
        limit: int = 500,
    ) -> list[LessonSession]:
        query = """
            SELECT *
            FROM lesson_sessions
            WHERE user_id = ? AND deleted_at IS NULL
        """
        params: list[object] = [user_id]
        if updated_after:
            query += " AND server_updated_at > ?"
            params.append(updated_after)
        query += " ORDER BY server_updated_at ASC LIMIT ?"
        params.append(limit)

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
            return [self._lesson_session_from_row(row) for row in rows]

    def get_lesson_session(self, *, user_id: int, lesson_id: str) -> LessonSession | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
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
            connection.commit()

        session = self.get_lesson_session(user_id=user_id, lesson_id=lesson_id)
        if session is None:
            raise RuntimeError("Lesson session upsert did not return a row.")
        return session

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
        )


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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
