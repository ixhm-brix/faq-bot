"""Show what's currently in the ChromaDB collection."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag.store import get_collection


def main():
    coll = get_collection()
    n = coll.count()
    print(f"Total chunks: {n}")
    if n == 0:
        return
    result = coll.get()
    by_source: dict[str, int] = {}
    null_meta = 0
    for meta in result["metadatas"]:
        if meta is None:
            null_meta += 1
            continue
        src = meta.get("source", "<no source key>")
        by_source[src] = by_source.get(src, 0) + 1
    print(f"Chunks with null metadata: {null_meta}")
    print("By source:")
    for s, c in sorted(by_source.items()):
        print(f"  {s}: {c}")


if __name__ == "__main__":
    main()
