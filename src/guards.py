"""Everything that decides NOT to call DeepSeek.

Ordered cheapest-first, because the whole point is that the common rejections cost
nothing. A junk message, a flood, or a tripped breaker must never reach the API.

    reject_locally()  — shape of the message. Free, no state.
    RateLimiter       — per-IP flood control. In-memory.
    CircuitBreaker    — global daily ceiling. The real bill protection.

Why the breaker exists on top of rate limiting: rate limits are per-IP, and anyone
determined enough to abuse this rotates IPs. The daily cap is the only control that
bounds the total spend regardless of where traffic comes from. When it trips the
widget still works — it serves published content and the WhatsApp handoff.

State is in-process and resets on restart. That is a deliberate trade for a
single-instance service on a small VPS: no Redis, no extra moving part. If this ever
runs more than one worker, these become per-worker and want moving to shared storage.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from src.config import (
    DAILY_API_CALL_CAP,
    MAX_INPUT_CHARS,
    RATE_LIMIT_PER_DAY,
    RATE_LIMIT_PER_MINUTE,
)

# --- Local pre-filter -----------------------------------------------------

# Only rejections that are unambiguous and cheap live here.
#
# There is deliberately NO greeting/thanks word list. "hi" was easy; "yooo",
# "heyyy", "wassup", "hi there boss" are not, and any list you write will miss the
# next variation and answer a real person with a shrug. Recognising conversational
# openers is exactly what the model is good at, and one greeting costs a mostly
# cached request. Correctness beats saving a fraction of a cent.
#
# What stays here is what cannot be misread: nothing typed, nothing but
# punctuation, or more than we will accept in one message.

TOO_SHORT_REPLY = (
    "Could you give me a bit more to go on? Ask about prices, timing, or what you "
    "end up owning."
)
TOO_LONG_REPLY = (
    "That is longer than I can take in one message. Could you shorten it to the "
    "main question?"
)


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", text.lower()).strip()


def reject_locally(text: str) -> str | None:
    """A canned reply when the message cannot be a question at all, else None.

    Kept deliberately narrow — see the note above. Anything with letters in it
    goes to the model, including greetings, thanks and small talk.
    """
    stripped = (text or "").strip()
    if not stripped:
        return TOO_SHORT_REPLY

    if len(stripped) > MAX_INPUT_CHARS:
        return TOO_LONG_REPLY

    # No letters anywhere: "???", "123", "...". Nothing to answer.
    if not re.search(r"[^\W\d_]", stripped, flags=re.UNICODE):
        return TOO_SHORT_REPLY

    return None


# --- Per-IP rate limiting -------------------------------------------------


class RateLimiter:
    """Sliding-window counter per key, with a minute and a day bound."""

    def __init__(self) -> None:
        self._minute: dict[str, deque[float]] = defaultdict(deque)
        self._day: dict[str, deque[float]] = defaultdict(deque)

    def _trim(self, bucket: deque[float], window: float, now: float) -> None:
        while bucket and now - bucket[0] > window:
            bucket.popleft()

    def allow(self, key: str) -> bool:
        now = time.time()
        minute, day = self._minute[key], self._day[key]
        self._trim(minute, 60, now)
        self._trim(day, 86_400, now)
        if len(minute) >= RATE_LIMIT_PER_MINUTE or len(day) >= RATE_LIMIT_PER_DAY:
            return False
        minute.append(now)
        day.append(now)
        return True

    def sweep(self, now: float | None = None) -> None:
        """Drop keys with no recent activity so the dicts don't grow forever."""
        now = now or time.time()
        for store, window in ((self._minute, 60), (self._day, 86_400)):
            for key in [k for k, v in store.items() if not v or now - v[-1] > window]:
                store.pop(key, None)


# --- Global daily circuit breaker ----------------------------------------


class CircuitBreaker:
    """Counts API calls and refuses once the daily cap is reached.

    Resets at UTC midnight. Counting happens on *attempt*, not success, so a burst
    of failing calls still consumes budget — a failing upstream should not become an
    unbounded retry loop against a paid API.
    """

    def __init__(self, cap: int = DAILY_API_CALL_CAP) -> None:
        self.cap = cap
        self._count = 0
        self._day = self._today()

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _roll(self) -> None:
        today = self._today()
        if today != self._day:
            self._day = today
            self._count = 0

    def is_open(self) -> bool:
        """True when the breaker has tripped and calls must stop."""
        self._roll()
        return self._count >= self.cap

    def record(self) -> None:
        self._roll()
        self._count += 1

    @property
    def used(self) -> int:
        self._roll()
        return self._count

    def status(self) -> dict:
        self._roll()
        return {"used": self._count, "cap": self.cap, "day": self._day, "open": self.is_open()}


rate_limiter = RateLimiter()
breaker = CircuitBreaker()
