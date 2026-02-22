"""SQLite-backed persistent memory store."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    sender TEXT NOT NULL,
    text TEXT NOT NULL,
    ts TEXT NOT NULL,
    intent TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    category TEXT NOT NULL,
    text TEXT NOT NULL,
    source_id INTEGER REFERENCES messages(id),
    ts TEXT NOT NULL,
    active INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_messages_project ON messages(project);
CREATE INDEX IF NOT EXISTS idx_knowledge_project ON knowledge(project);
CREATE INDEX IF NOT EXISTS idx_knowledge_active ON knowledge(project, active);
"""


class MemoryStore:
    """SQLite-backed store for messages and knowledge entries."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection = sqlite3.connect(
            self._db_path, check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def __enter__(self) -> MemoryStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def log_message(
        self,
        project: str,
        sender: str,
        text: str,
        intent: str = "",
        ts: str | None = None,
    ) -> int:
        """Insert a message and return its row ID."""
        if ts is None:
            ts = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            "INSERT INTO messages (project, sender, text, ts, intent) VALUES (?, ?, ?, ?, ?)",
            (project, sender, text, ts, intent),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_messages(
        self,
        project: str,
        limit: int = 50,
        sender: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve messages for a project, newest first."""
        if sender:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE project = ? AND sender = ? ORDER BY id DESC LIMIT ?",
                (project, sender, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE project = ? ORDER BY id DESC LIMIT ?",
                (project, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def log_knowledge(
        self,
        project: str,
        category: str,
        text: str,
        source_id: int | None = None,
    ) -> int:
        """Insert a knowledge entry and return its row ID."""
        ts = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            "INSERT INTO knowledge (project, category, text, source_id, ts) VALUES (?, ?, ?, ?, ?)",
            (project, category, text, source_id, ts),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_knowledge(
        self,
        project: str,
        category: str | None = None,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Retrieve knowledge entries for a project."""
        conditions = ["project = ?"]
        params: list[Any] = [project]
        if category:
            conditions.append("category = ?")
            params.append(category)
        if active_only:
            conditions.append("active = 1")
        where = " AND ".join(conditions)
        rows = self._conn.execute(
            f"SELECT * FROM knowledge WHERE {where} ORDER BY id DESC",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def deactivate_knowledge(self, knowledge_id: int) -> bool:
        """Mark a knowledge entry as inactive. Returns True if a row was updated."""
        cursor = self._conn.execute(
            "UPDATE knowledge SET active = 0 WHERE id = ? AND active = 1",
            (knowledge_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def search_messages(
        self,
        project: str,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search messages by text (SQL LIKE)."""
        pattern = f"%{query}%"
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE project = ? AND text LIKE ? ORDER BY id DESC LIMIT ?",
            (project, pattern, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_stats(self, project: str) -> dict[str, int]:
        """Return message and knowledge counts for a project."""
        msg_count = self._conn.execute(
            "SELECT COUNT(*) FROM messages WHERE project = ?", (project,),
        ).fetchone()[0]
        know_count = self._conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE project = ? AND active = 1", (project,),
        ).fetchone()[0]
        return {"messages": msg_count, "knowledge": know_count}


_store_instance: MemoryStore | None = None


def get_store() -> MemoryStore:
    """Get or create the singleton MemoryStore using configured path."""
    global _store_instance
    if _store_instance is None:
        from hookline.config import MEMORY_DB_PATH, STATE_DIR
        db_path = MEMORY_DB_PATH if MEMORY_DB_PATH else str(STATE_DIR / "memory.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _store_instance = MemoryStore(db_path)
    return _store_instance
