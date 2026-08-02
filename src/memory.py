import sqlite3
import time
import re
from dataclasses import dataclass
from pathlib import Path

from src.config import HISTORY_CHAR_CAP, HISTORY_TURNS

MEMORY_DB_PATH = Path("data/conversation_memory.sqlite3")
MEMORY_TTL_SECONDS = 12 * 60 * 60
MAX_HISTORY_MESSAGES = 20
MAX_MEMORY_RECALL_ITEMS = 5
MAX_CONTEXT_MESSAGES = 8
MAX_CONTEXT_MESSAGE_CHARS = 320


@dataclass
class ChatMessage:
    role: str
    content: str
    created_at: float


def _connect() -> sqlite3.Connection:
    MEMORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(MEMORY_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_time
        ON chat_messages (chat_id, created_at)
        """
    )
    return conn


def _cutoff(now: float | None = None) -> float:
    return (now or time.time()) - MEMORY_TTL_SECONDS


def cleanup_expired(now: float | None = None) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM chat_messages WHERE created_at < ?", (_cutoff(now),))


def get_recent_messages(chat_id: int | str) -> list[ChatMessage]:
    """The conversation window sent to the model: last HISTORY_TURNS exchanges.

    This used to return up to 20 messages spanning 12 hours, and every one of them
    was re-sent on every request — the single largest silent token drain in the
    service, and it grew the longer someone chatted. A few turns is all that is
    needed to resolve "what about the second one?"; anything older is answered
    just as well from the knowledge base, which is sent in full regardless.

    Two caps apply, whichever bites first: a message count, and a total character
    budget so one pasted wall of text cannot blow the window open.
    """
    cleanup_expired()
    limit = max(2, HISTORY_TURNS * 2)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT role, content, created_at
            FROM chat_messages
            WHERE chat_id = ? AND created_at >= ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (str(chat_id), _cutoff(), limit),
        ).fetchall()

    # rows are newest-first; keep newest and walk back until the budget is spent
    kept: list[ChatMessage] = []
    budget = HISTORY_CHAR_CAP
    for role, content, created_at in rows:
        text = content or ""
        if len(text) > budget:
            break
        budget -= len(text)
        kept.append(ChatMessage(role=role, content=text, created_at=created_at))

    return list(reversed(kept))


def remember_message(chat_id: int | str, role: str, content: str) -> None:
    if role not in {"user", "assistant"}:
        raise ValueError("role must be 'user' or 'assistant'")

    cleaned = content.strip()
    if not cleaned:
        return

    cleanup_expired()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_messages (chat_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(chat_id), role, cleaned, time.time()),
        )


def _shorten(text: str, max_chars: int = MAX_CONTEXT_MESSAGE_CHARS) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rsplit(" ", 1)[0].rstrip() + "..."


def build_retrieval_query(question: str, history: list[ChatMessage]) -> str:
    recent_messages: list[str] = []
    for message in history[-MAX_CONTEXT_MESSAGES:]:
        if message.role == "user" and (
            is_memory_question(message.content)
            or _is_low_signal_user_message(message.content)
        ):
            continue
        recent_messages.append(f"{message.role}: {_shorten(message.content)}")

    if not recent_messages:
        return question

    return (
        "Recent conversation:\n"
        + "\n".join(recent_messages)
        + f"\n\nCurrent question:\n{question}"
    )


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", text.lower()).strip()


def is_memory_question(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", _normalize(text))
    if not normalized:
        return False

    memory_phrases = (
        "do you remember",
        "what did i ask",
        "what have i asked",
        "what was my last question",
        "what is my last question",
        "what did i say",
        "what have i said",
        "my previous question",
        "previous question",
        "last question",
        "recap our conversation",
        "summarize our conversation",
        "conversation summary",
    )
    return any(phrase in normalized for phrase in memory_phrases)


def _is_low_signal_user_message(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", _normalize(text))
    return normalized in {
        "hi",
        "hii",
        "hello",
        "hey",
        "ok",
        "okay",
        "thanks",
        "thank you",
        "got it",
    }


def build_memory_answer(history: list[ChatMessage]) -> str:
    user_messages = [
        message.content
        for message in history
        if (
            message.role == "user"
            and not is_memory_question(message.content)
            and not _is_low_signal_user_message(message.content)
        )
    ]

    if not user_messages:
        return (
            "I can remember this chat for 12 hours, but I don't have an earlier "
            "question from you yet."
        )

    recent = user_messages[-MAX_MEMORY_RECALL_ITEMS:]
    lines = "\n".join(f"- {message}" for message in recent)
    return (
        "Yes. In this chat, within the last 12 hours, you asked:\n\n"
        f"{lines}"
    )
