"""Portal user authentication.

SQLite-backed users table with bcrypt-hashed passwords. Replaces the
previous single-user-from-.env login.

Migration: if the table is empty when the portal starts, we bootstrap an
initial user from PORTAL_ADMIN_USERNAME / PORTAL_ADMIN_PASSWORD so
existing deployments keep working. Fresh installs without those env vars
get the /signup flow instead.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import bcrypt

DB_PATH = Path("data/users.db")


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    return conn


def user_count() -> int:
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def username_taken(username: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username.strip().lower(),)
        ).fetchone()
    return row is not None


def create_user(username: str, password: str) -> None:
    """Create a user. Raises sqlite3.IntegrityError if the username is taken."""
    clean = username.strip().lower()
    if not clean:
        raise ValueError("username required")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _conn() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (clean, pw_hash, now),
        )


def verify_password(username: str, password: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (username.strip().lower(),),
        ).fetchone()
    if not row:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8"))
    except ValueError:
        return False


def bootstrap_admin(env_username: str | None, env_password: str | None) -> None:
    """If the users table is empty and env credentials are present, seed an
    initial admin so existing deployments keep working without manual signup.
    Idempotent."""
    if not env_username or not env_password:
        return
    if user_count() > 0:
        return
    try:
        create_user(env_username, env_password)
    except (ValueError, sqlite3.IntegrityError):
        # invalid env creds (e.g. password too short) -> caller will see the
        # signup form instead; not worth crashing the portal at startup.
        pass
