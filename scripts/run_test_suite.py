r"""Run a batch of test questions through the real RAG pipeline and write a
report JSON that the portal renders at /report.

Questions: one per line in data/test_questions.txt (blank lines ignored;
lines starting with # are treated as comments and skipped).

Each question runs in its own fresh session, so answers reflect the
documents only — not earlier questions in the batch. (If you want them
treated as one continuous conversation instead, pass --conversation.)

Usage:
    .\.venv\Scripts\python.exe scripts\run_test_suite.py
    .\.venv\Scripts\python.exe scripts\run_test_suite.py --conversation
"""
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import chat
from src.chat import build_off_topic_reply
from src.llm import generate_followups

QUESTIONS_FILE = Path("data/test_questions.txt")
REPORT_FILE = Path("data/test_report.json")

HANDOFF_MSG = (
    "I couldn't find that in our documents, so the question was logged for "
    "the team to follow up."
)


async def main() -> None:
    conversation = "--conversation" in sys.argv

    if not QUESTIONS_FILE.exists():
        print(f"No questions file. Create {QUESTIONS_FILE} (one question per line).")
        return

    # Parse questions, honoring [[conversation]] ... [[/conversation]] blocks
    # whose questions share one session (run in order). Everything else is
    # independent, unless --conversation forces one global session.
    shared_session = f"test:{uuid.uuid4().hex[:8]}"
    items = []  # (question, session_id)
    in_conv = False
    conv_sid = None
    for ln in QUESTIONS_FILE.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        low = s.lower()
        if low == "[[conversation]]":
            in_conv, conv_sid = True, f"test-conv:{uuid.uuid4().hex[:8]}"
            continue
        if low == "[[/conversation]]":
            in_conv, conv_sid = False, None
            continue
        if conversation:
            sid = shared_session
        elif in_conv:
            sid = conv_sid
        else:
            sid = f"test:{uuid.uuid4().hex[:8]}"
        items.append((s, sid))

    if not items:
        print("Questions file is empty.")
        return

    print(f"Running {len(items)} questions"
          + (" as one conversation" if conversation else " (independent + conversation blocks)") + "...\n")

    results = []
    t0 = time.time()

    for i, (q, sid) in enumerate(items, 1):
        start = time.time()
        followups = []
        try:
            r = await chat.answer_message(sid, q)
            if r.is_security:
                outcome, reply = "security", chat.build_security_reply()
            elif r.is_off_topic:
                outcome, reply = "off_topic", build_off_topic_reply()
            elif r.is_handoff:
                # Partial-answer handoffs carry helpful text; show it.
                outcome, reply = "handoff", (r.text or HANDOFF_MSG)
            else:
                outcome, reply = "answered", r.text
                try:
                    followups = await generate_followups(q, r.text, r.chunks_used)
                except Exception:
                    followups = []
            chunks = len(r.chunks_used)
        except Exception as e:  # keep going through the whole batch
            outcome, reply, chunks = "error", f"ERROR: {e}", 0
        ms = int((time.time() - start) * 1000)
        results.append({
            "n": i, "question": q, "reply": reply,
            "outcome": outcome, "chunks": chunks, "ms": ms,
            "followups": followups,
        })
        print(f"[{i}/{len(items)}] {outcome:9} {ms:5}ms  {q[:64]}")

    summary = {
        "total": len(results),
        "answered": sum(1 for r in results if r["outcome"] == "answered"),
        "handoff": sum(1 for r in results if r["outcome"] == "handoff"),
        "off_topic": sum(1 for r in results if r["outcome"] == "off_topic"),
        "security": sum(1 for r in results if r["outcome"] == "security"),
        "error": sum(1 for r in results if r["outcome"] == "error"),
        "elapsed_s": round(time.time() - t0, 1),
        "mode": "conversation" if conversation else "independent",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(
        json.dumps({"summary": summary, "results": results}, indent=2),
        encoding="utf-8",
    )
    print("\nDone.")
    print(f"  answered={summary['answered']}  handoff={summary['handoff']}  "
          f"off_topic={summary['off_topic']}  security={summary['security']}  "
          f"error={summary['error']}")
    print(f"  Report written to {REPORT_FILE}. View it at http://127.0.0.1:8000/report")


if __name__ == "__main__":
    asyncio.run(main())
