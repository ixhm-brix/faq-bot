"""Smoke-test: does the bot really resolve follow-up questions using prior chat?

Simulates a 2-turn conversation and prints:
  (a) what `build_retrieval_query` produces,
  (b) which chunks come back vs. retrieving the bare follow-up alone,
  (c) what DeepSeek answers when given the rewritten query + history.

If (b) shows the expanded query surfaces relevant chunks the bare query misses,
the follow-up plumbing works. If both queries return the same chunks, the
history isn't actually helping retrieval — we'd need real query rewriting.
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm import answer
from src.memory import ChatMessage, build_retrieval_query
from src.rag.retrieve import retrieve


PAIRS = [
    ("What are your working hours?", "What about Saturday?"),
    ("How do I apply?", "When's the deadline?"),
    ("How much is tuition?", "What payment methods do you accept?"),
]


def fake_assistant_reply(question: str) -> str:
    """Fill in a plausible reply so the bot's history makes sense."""
    return f"(prior reply to: '{question}')"


def print_chunks(label: str, chunks: list) -> None:
    print(f"  -- {label}: {len(chunks)} chunk(s)")
    for c in chunks[:3]:
        snippet = c.text.replace("\n", " ")[:120]
        print(f"     [{c.distance:.3f}] {snippet}...")


async def main() -> None:
    for q1, q2 in PAIRS:
        print(f"\n=== Q1: {q1!r}  ->  Q2: {q2!r} ===")
        now = time.time()
        history = [
            ChatMessage(role="user", content=q1, created_at=now - 60),
            ChatMessage(role="assistant", content=fake_assistant_reply(q1), created_at=now - 30),
        ]

        bare_chunks = retrieve(q2)
        print_chunks("retrieval on Q2 alone", bare_chunks)

        expanded_query = build_retrieval_query(q2, history)
        print(f"\n  build_retrieval_query output (truncated):")
        for line in expanded_query.splitlines():
            print(f"    | {line[:200]}")

        expanded_chunks = retrieve(expanded_query)
        print()
        print_chunks("retrieval on Q2 + history", expanded_chunks)

        reply = await answer(q2, expanded_chunks, history)
        print(f"\n  DeepSeek reply:\n    {reply[:400]}")


if __name__ == "__main__":
    asyncio.run(main())
