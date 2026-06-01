import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("data/handoffs.db")


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS handoffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            question TEXT NOT NULL,
            user_chat_id INTEGER NOT NULL,
            user_username TEXT,
            user_full_name TEXT,
            status TEXT NOT NULL DEFAULT 'open'
        )
        """
    )
    return conn


def record(question: str, user_chat_id: int, user_username: str | None, user_full_name: str | None) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO handoffs (created_at, question, user_chat_id, user_username, user_full_name)"
            " VALUES (?, ?, ?, ?, ?)",
            (now, question, user_chat_id, user_username, user_full_name),
        )
        return cur.lastrowid


def list_all(status: str | None = None) -> list[dict]:
    with _conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM handoffs WHERE status=? ORDER BY id DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM handoffs ORDER BY id DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def open_count() -> int:
    with _conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM handoffs WHERE status='open'"
        ).fetchone()[0]


def mark_resolved(handoff_id: int) -> None:
    with _conn() as conn:
        conn.execute("UPDATE handoffs SET status='resolved' WHERE id=?", (handoff_id,))
