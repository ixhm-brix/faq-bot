r"""Parse test.txt (numbered questions with section headers) into
data/test_questions.txt that the runner understands.

Questions 81-100 are the four conversation blocks from the file; we wrap
each in [[conversation]] ... [[/conversation]] so the runner replays them
in one session, in order. Everything else stays independent.

Usage: .\.venv\Scripts\python.exe scripts\prep_test_questions.py
"""
import re
from pathlib import Path

SRC = Path("test.txt")
OUT = Path("data/test_questions.txt")

# (start, end) inclusive ranges that must run as one continuous conversation
CONV_GROUPS = [(81, 85), (86, 90), (91, 95), (96, 100)]


def group_of(n: int):
    for a, b in CONV_GROUPS:
        if a <= n <= b:
            return (a, b)
    return None


def main() -> None:
    if not SRC.exists():
        print(f"{SRC} not found.")
        return
    pairs = []
    for line in SRC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*(\d+)\.\s+(.*\S)\s*$", line)
        if m:
            pairs.append((int(m.group(1)), m.group(2)))
    pairs.sort()
    by_n = dict(pairs)

    out = []
    open_group = None
    for n in range(1, (max(by_n) if by_n else 0) + 1):
        if n not in by_n:
            continue
        g = group_of(n)
        if g != open_group:
            if open_group:
                out.append("[[/conversation]]")
            if g:
                out.append("[[conversation]]")
            open_group = g
        out.append(by_n[n])
    if open_group:
        out.append("[[/conversation]]")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    n_q = sum(1 for l in out if not l.startswith("[["))
    print(f"Wrote {n_q} questions to {OUT} "
          f"({len(CONV_GROUPS)} conversation blocks).")


if __name__ == "__main__":
    main()
