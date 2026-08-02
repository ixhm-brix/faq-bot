"""The human handoff, and what the widget shows when the assistant can't run.

WhatsApp is a person, deliberately — there is no bot on the other end. Someone who
leaves the widget to open WhatsApp has decided they want a human, and meeting them
with a second bot would frustrate exactly the people already unsatisfied.

The visitor's question is carried across in the prefilled message so the
conversation opens with what they actually asked, instead of "hi, how can I help".

OFFLINE FALLBACK — note what this deliberately does NOT do.

When the API is unreachable, over quota, or the daily breaker has tripped, the
widget SHOWS published content: the price list and the top questions, lifted
verbatim from the same knowledge base the site generates. It does not run a second
local question-matcher. A keyword matcher that picks the wrong FAQ entry would
answer a pricing question with the wrong price and look authoritative doing it —
strictly worse than plainly saying "I can't answer right now, here is the price
list, here is a person".
"""
from __future__ import annotations

import re
from urllib.parse import quote

from src.config import WHATSAPP_NUMBER
from src.kb import kb_text

OFFLINE_MESSAGE = (
    "I can't reach my answering service right now. Here is what we publish, and "
    "you can reach a person on WhatsApp."
)

HANDOFF_MESSAGE = (
    "That isn't something we publish an answer for, so I'd rather not guess. "
    "A person can answer it properly on WhatsApp."
)


def whatsapp_url(question: str = "") -> str | None:
    """Click-to-chat link, prefilled with what the visitor asked.

    Returns None when no number is configured, so callers can hide the button
    rather than render a dead link.
    """
    if not WHATSAPP_NUMBER:
        return None
    number = re.sub(r"\D", "", WHATSAPP_NUMBER)
    if not number:
        return None

    asked = " ".join((question or "").split())[:300]
    text = (
        f"Hi briqx — I asked Munyakazi on your site: {asked}"
        if asked
        else "Hi briqx — I have a question about your work."
    )
    return f"https://wa.me/{number}?text={quote(text)}"


def _section(title: str) -> str:
    """Pull one '## title' section out of the KB verbatim."""
    pattern = rf"^## {re.escape(title)}\s*\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, kb_text(), flags=re.S | re.M)
    return match.group(1).strip() if match else ""


def offline_card(question: str = "") -> dict:
    """Published content to display when the assistant cannot answer.

    Content only — no matching, no interpretation.
    """
    prices = [
        line.lstrip("- ").strip()
        for line in _section("What we charge").splitlines()
        if line.strip().startswith("-")
    ]

    faq_block = _section("Questions we are asked")
    questions = [
        line[2:].strip() for line in faq_block.splitlines() if line.startswith("Q:")
    ][:5]

    return {
        "reply": OFFLINE_MESSAGE,
        "offline": True,
        "prices": prices,
        "questions": questions,
        "whatsapp": whatsapp_url(question),
        "followups": [],
    }
