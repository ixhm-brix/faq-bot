"""Quick sanity check: query the FAQ collection and print the top chunks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag.store import embed, get_collection

QUERIES = [
    "What are the library hours?",
    "How much is tuition?",
    "How do I contact the registrar?",
    "Is the moon made of cheese?",
]


def main():
    coll = get_collection()
    for q in QUERIES:
        print(f"\n=== Q: {q}")
        r = coll.query(query_embeddings=embed([q]), n_results=2)
        for i, (doc, dist) in enumerate(zip(r["documents"][0], r["distances"][0])):
            print(f"  [{i}] distance={dist:.3f}")
            print(f"      {doc[:200]}...")


if __name__ == "__main__":
    main()
