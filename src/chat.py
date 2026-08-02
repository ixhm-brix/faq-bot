"""Conversation core for the website widget.

Previously this was a channel-neutral RAG + memory pipeline shared by Telegram,
WhatsApp and the widget. Telegram has been retired and WhatsApp is now a human
handoff rather than a bot, so this serves one caller: POST /widget/chat.

The retrieval stage is gone. The knowledge base is ~1.9k tokens and is sent whole
inside the cached system block (see llm.py), so there is nothing to search and no
chance of grounding an answer on the wrong chunk.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.llm import (
    NO_CONTEXT_MARKER,
    OFF_TOPIC_MARKER,
    SECURITY_MARKER,
    SOFT_HANDOFF_MARKER,
    answer,
)
from src.memory import (
    build_memory_answer,
    get_recent_messages,
    is_memory_question,
    remember_message,
)

_ALL_MARKERS = (
    SOFT_HANDOFF_MARKER,
    NO_CONTEXT_MARKER,
    OFF_TOPIC_MARKER,
    SECURITY_MARKER,
)


def _strip_markers(text: str) -> str:
    """Remove any control-marker lines/tokens the model left in a reply."""
    kept = [ln for ln in text.splitlines() if ln.strip() not in _ALL_MARKERS]
    cleaned = "\n".join(kept)
    for marker in _ALL_MARKERS:
        cleaned = cleaned.replace(marker, "")
    return cleaned.strip()


@dataclass
class AnswerResult:
    text: str
    """Reply text. Empty when is_handoff/is_off_topic/is_security is set — the
    caller writes its own phrasing for those."""

    is_handoff: bool = False
    """A legitimate briqx question the published content doesn't cover. Offer the
    human handoff."""

    is_off_topic: bool = False
    """Not about briqx at all. Decline politely, do NOT escalate to a person."""

    is_security: bool = False
    """Prompt injection / credential fishing. Refuse without escalating."""


def build_off_topic_reply() -> str:
    return (
        "I only answer questions about briqx — what we build, what it costs, and "
        "how it works. Ask me one of those and I'll help."
    )


def build_security_reply() -> str:
    return (
        "I can only answer questions about briqx and what we build. Ask me about "
        "prices, timelines or what you end up owning."
    )


async def answer_message(session_id: str, text: str) -> AnswerResult:
    """Run one user turn. Caller has already applied guards.reject_locally()."""
    history = get_recent_messages(session_id)

    if is_memory_question(text):
        reply = build_memory_answer(history)
        remember_message(session_id, "user", text)
        remember_message(session_id, "assistant", reply)
        return AnswerResult(text=reply)

    llm_reply = await answer(text, history)
    remember_message(session_id, "user", text)

    # Order matters: SECURITY first (an attack that also looks off-topic should be
    # recorded as an attack), then OFF_TOPIC, then the handoff cases.
    if SECURITY_MARKER in llm_reply:
        return AnswerResult(text="", is_security=True)
    if OFF_TOPIC_MARKER in llm_reply:
        return AnswerResult(text="", is_off_topic=True)
    if NO_CONTEXT_MARKER in llm_reply:
        return AnswerResult(text="", is_handoff=True)
    if SOFT_HANDOFF_MARKER in llm_reply:
        # Partial answer: keep what was useful AND flag the handoff.
        partial = _strip_markers(llm_reply)
        if not partial:
            return AnswerResult(text="", is_handoff=True)
        return AnswerResult(text=partial, is_handoff=True)

    remember_message(session_id, "assistant", llm_reply)
    return AnswerResult(text=llm_reply)
