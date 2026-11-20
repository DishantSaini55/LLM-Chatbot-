"""A deliberately small SQLite repository.

The assignment asks for SQLite, so the standard library is enough.  Opening a
short-lived connection per operation also avoids sharing a SQLite connection
between FastAPI worker threads.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator


def database_path(database_url: str) -> str:
    """Convert the allowed sqlite URL format into a filesystem path."""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("DATABASE_URL must use sqlite:///")
    path = database_url[len(prefix) :]
    if not path:
        raise ValueError("DATABASE_URL must contain a file path")
    return path


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, url: str) -> None:
        self.path = database_path(url)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # /data is mounted as a named Docker volume.  The same code also works
        # with a relative path when running without Docker.
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    system_prompt TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session_created
                    ON messages(session_id, id);
                """
            )

    def ping(self) -> bool:
        try:
            with self._connection() as connection:
                connection.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    def get_system_prompt(self, session_id: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT system_prompt FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return None if row is None else str(row["system_prompt"])

    def session_exists(self, session_id: str) -> bool:
        with self._connection() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
                is not None
            )

    def get_messages(self, session_id: str) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT role, content, metadata, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()

        messages: list[dict[str, object]] = []
        for row in rows:
            item: dict[str, object] = {
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
            if row["metadata"] is not None:
                item["metadata"] = json.loads(row["metadata"])
            messages.append(item)
        return messages

    def save_successful_turn(
        self,
        *,
        session_id: str,
        system_prompt: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, object],
    ) -> None:
        """Persist both chat messages in one transaction after a successful call."""
        timestamp = utc_now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO sessions (session_id, system_prompt, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    system_prompt = excluded.system_prompt,
                    updated_at = excluded.updated_at
                """,
                (session_id, system_prompt, timestamp, timestamp),
            )
            connection.execute(
                """
                INSERT INTO messages (session_id, role, content, metadata, created_at)
                VALUES (?, 'user', ?, NULL, ?)
                """,
                (session_id, user_message, timestamp),
            )
            connection.execute(
                """
                INSERT INTO messages (session_id, role, content, metadata, created_at)
                VALUES (?, 'assistant', ?, ?, ?)
                """,
                (
                    session_id,
                    assistant_message,
                    json.dumps(metadata, separators=(",", ":")),
                    timestamp,
                ),
            )
