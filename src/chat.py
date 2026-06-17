"""Channel-neutral conversation core.

The Telegram bot, the website widget, and (future) WhatsApp / email all
share the same RAG + memory pipeline. This module is that pipeline,
stripped of any channel-specific UX (typing indicators, inline buttons,
HTML formatting). Each channel adapter calls `answer_message()` and
renders the result the way that channel renders things.

Session IDs are arbitrary strings — for Telegram we use the chat_id, for
the widget we use a UUID prefixed with `web:` to avoid collision. The
memory module treats them as opaque strings.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.llm import (
    NO_CONTEXT_MARKER,
    OFF_TOPIC_MARKER,
    SECURITY_MARKER,
    SOFT_HANDOFF_MARKER,
    answer,
)

_ALL_MARKERS = (
    SOFT_HANDOFF_MARKER,
    NO_CONTEXT_MARKER,
    OFF_TOPIC_MARKER,
    SECURITY_MARKER,
)


def _strip_markers(text: str) -> str:
    """Remove any control-marker lines/tokens the model left in a reply."""
    kept = [
        ln for ln in text.splitlines()
        if ln.strip() not in _ALL_MARKERS
    ]
    cleaned = "\n".join(kept)
    for marker in _ALL_MARKERS:
        cleaned = cleaned.replace(marker, "")
    return cleaned.strip()
from src.memory import (
    build_memory_answer,
    build_retrieval_query,
    get_recent_messages,
    is_memory_question,
    remember_message,
)
from src.rag.retrieve import RetrievedChunk, confidence_for, retrieve
from src.settings import get_suggested_questions


@dataclass
class AnswerResult:
    text: str
    """Raw text reply for grounded answers / memory recall. Empty when
    is_handoff or is_off_topic is True — the channel adapter writes its
    own phrasing in those cases."""

    is_handoff: bool = False
    """True when the LLM declined to answer because the docs don't cover
    a *legitimate* question for this org. Caller should record the
    question with src.handoff.record() and show a handoff message."""

    is_off_topic: bool = False
    """True when the LLM declined because the question is clearly not
    about this organization at all (e.g. 'what's the HTML tag for an
    image?'). Caller should politely decline WITHOUT escalating to
    staff — nobody at the org should be answering those."""

    is_security: bool = False
    """True when the message was a prompt-injection / jailbreak attempt
    (override instructions, extract the system prompt or private docs,
    obtain credentials). Caller refuses WITHOUT escalating, and may log
    it separately for monitoring."""

    chunks_used: list[RetrievedChunk] = field(default_factory=list)
    """The chunks that grounded the answer. Caller may pass these to
    src.llm.generate_followups() to render follow-up suggestion buttons."""

    confidence: str = ""
    """Retrieval confidence for this turn: "high" | "medium" | "low" |
    "none" | "". Drives how cautiously the bot answered; surfaced in the
    QA report. Empty for greeting/memory turns that skip retrieval."""


async def answer_message(session_id: str, text: str) -> AnswerResult:
    """Run the full RAG + memory pipeline for one user turn.

    Stores the user's message in memory regardless of outcome; only stores
    the assistant reply in memory when there is a real reply (not on the
    handoff branch — the channel's handoff phrasing is the channel's
    concern and shouldn't bleed into other channels' memory).
    """
    history = get_recent_messages(session_id)

    if is_memory_question(text):
        reply = build_memory_answer(history)
        remember_message(session_id, "user", text)
        remember_message(session_id, "assistant", reply)
        return AnswerResult(text=reply)

    retrieval_query = build_retrieval_query(text, history)
    chunks = retrieve(retrieval_query)
    confidence = confidence_for(chunks)
    llm_reply = await answer(text, chunks, history, confidence=confidence)

    remember_message(session_id, "user", text)

    # Order matters: SECURITY first (a jailbreak that also looks off-topic
    # should be flagged as a security event), then OFF_TOPIC, then the
    # full/partial handoff cases.
    if SECURITY_MARKER in llm_reply:
        return AnswerResult(text="", is_security=True, chunks_used=[])
    if OFF_TOPIC_MARKER in llm_reply:
        return AnswerResult(text="", is_off_topic=True, chunks_used=[])
    if NO_CONTEXT_MARKER in llm_reply:
        # Nothing relevant in the docs at all → full handoff, no text.
        return AnswerResult(text="", is_handoff=True, chunks_used=[], confidence=confidence)
    if SOFT_HANDOFF_MARKER in llm_reply:
        # Partial answer: the model gave related info but the exact answer
        # needs a human. Keep the helpful text AND flag the handoff.
        partial = _strip_markers(llm_reply)
        if not partial:
            return AnswerResult(text="", is_handoff=True, chunks_used=[], confidence=confidence)
        return AnswerResult(text=partial, is_handoff=True, chunks_used=chunks, confidence=confidence)

    remember_message(session_id, "assistant", llm_reply)
    return AnswerResult(text=llm_reply, chunks_used=chunks, confidence=confidence)


def build_security_reply() -> str:
    """Refusal for prompt-injection / jailbreak attempts. Polite, firm,
    no escalation, and reveals nothing about the system."""
    return (
        "I can only help with questions about this organization, and I can't "
        "share my internal instructions or any private information. "
        "Is there something about our services I can help you with?"
    )


def build_off_topic_reply() -> str:
    """Polite decline for questions that aren't about this organization.

    Doesn't escalate — these aren't questions staff should be paged on.
    Surfaces a couple of the configured suggestion questions as
    examples of what *is* in scope.
    """
    suggestions = get_suggested_questions()
    base = (
        "I'm here to answer questions about our organization, so I can't help "
        "with that one."
    )
    if suggestions:
        examples = "\n".join(f"- {q}" for q in suggestions[:3])
        return f"{base} You could try asking me things like:\n\n{examples}"
    return f"{base} Try asking me about something we offer or do."
