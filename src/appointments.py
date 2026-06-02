import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("data/appointments.db")

VALID_STATUSES = ("pending", "confirmed", "completed", "cancelled")


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            reason TEXT NOT NULL,
            slot_iso TEXT NOT NULL,
            slot_display TEXT NOT NULL,
            user_chat_id INTEGER NOT NULL,
            user_username TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
        )
        """
    )
    return conn


def record(
    *,
    name: str,
    phone: str,
    reason: str,
    slot_iso: str,
    slot_display: str,
    user_chat_id: int,
    user_username: str | None,
) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO appointments "
            "(created_at, name, phone, reason, slot_iso, slot_display, user_chat_id, user_username) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (now, name, phone, reason, slot_iso, slot_display, user_chat_id, user_username),
        )
        return cur.lastrowid


def list_all(status: str | None = None) -> list[dict]:
    with _conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM appointments WHERE status=? ORDER BY slot_iso DESC, id DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM appointments ORDER BY slot_iso DESC, id DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def pending_count() -> int:
    with _conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM appointments WHERE status='pending'"
        ).fetchone()[0]


def set_status(appointment_id: int, status: str) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    with _conn() as conn:
        conn.execute(
            "UPDATE appointments SET status=? WHERE id=?",
            (status, appointment_id),
        )
