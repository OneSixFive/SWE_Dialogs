from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class User:
    id: int
    apple_sub: str
    email: str | None


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    apple_sub TEXT NOT NULL UNIQUE,
                    email TEXT,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def find_or_create_user(self, apple_sub: str, email: str | None) -> User:
        now = datetime.now(UTC).isoformat()
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
