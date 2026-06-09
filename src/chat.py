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

from src.llm import NO_CONTEXT_MARKER, answer
from src.memory import (
    build_memory_answer,
    build_retrieval_query,
    get_recent_messages,
    is_memory_question,
    remember_message,
)
from src.rag.retrieve import RetrievedChunk, retrieve


@dataclass
class AnswerResult:
    text: str
    """Raw text reply for grounded answers / memory recall. Empty when
    is_handoff is True — the channel adapter writes its own phrasing
    (e.g. 'I've forwarded your question to our team')."""

    is_handoff: bool = False
    """True when the LLM declined to answer from the docs. Caller should
    record the question with src.handoff.record() and show a handoff
    message in the channel's UI."""

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

    if NO_CONTEXT_MARKER in llm_reply:
        return AnswerResult(text="", is_handoff=True, chunks_used=[])

    remember_message(session_id, "assistant", llm_reply)
    return AnswerResult(text=llm_reply, chunks_used=chunks)
