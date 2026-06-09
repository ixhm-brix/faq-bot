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

from src.llm import NO_CONTEXT_MARKER, OFF_TOPIC_MARKER, answer
from src.memory import (
    build_memory_answer,
    build_retrieval_query,
    get_recent_messages,
    is_memory_question,
    remember_message,
)
from src.rag.retrieve import RetrievedChunk, retrieve
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

    chunks_used: list[RetrievedChunk] = field(default_factory=list)
    """The chunks that grounded the answer. Caller may pass these to
    src.llm.generate_followups() to render follow-up suggestion buttons."""


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
    llm_reply = await answer(text, chunks, history)

    remember_message(session_id, "user", text)

    # Order matters: OFF_TOPIC takes precedence over NO_ANSWER_IN_DOCS so a
    # model that emits both still routes to the polite decline.
    if OFF_TOPIC_MARKER in llm_reply:
        return AnswerResult(text="", is_off_topic=True, chunks_used=[])
    if NO_CONTEXT_MARKER in llm_reply:
        return AnswerResult(text="", is_handoff=True, chunks_used=[])

    remember_message(session_id, "assistant", llm_reply)
    return AnswerResult(text=llm_reply, chunks_used=chunks)


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
