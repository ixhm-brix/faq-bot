from dataclasses import dataclass

from src.rag.store import embed, get_collection
from src.settings import get_retrieval_threshold


@dataclass
class RetrievedChunk:
    text: str
    source: str
    distance: float


def retrieve(query: str, k: int = 6) -> list[RetrievedChunk]:
    coll = get_collection()
    if coll.count() == 0:
        return []
    result = coll.query(
        query_embeddings=embed([query]),
        n_results=k,
    )
    docs = result["documents"][0]
    metas = result["metadatas"][0]
    dists = result["distances"][0]
    threshold = get_retrieval_threshold()
    chunks: list[RetrievedChunk] = []
    for d, m, dist in zip(docs, metas, dists):
        if not d or dist >= threshold:
            continue
        chunks.append(
            RetrievedChunk(
                text=d,
                source=(m or {}).get("source", "?"),
                distance=dist,
            )
        )
    return chunks


# Confidence bands scale off the configured "no match" threshold, so they
# auto-adjust when an admin tunes match strictness for a denser/looser corpus.
# best distance ≤ 70% of threshold → HIGH, ≤ 88% → MEDIUM, otherwise LOW.
# (Tuned for all-MiniLM-L6-v2, whose distances sit high even for clear hits.)
HIGH_CONFIDENCE_RATIO = 0.70
MEDIUM_CONFIDENCE_RATIO = 0.88


def confidence_for(chunks: list[RetrievedChunk]) -> str:
    """Classify how well the retrieved chunks match the query.

    Returns one of: "high", "medium", "low", "none". The LLM uses this to
    calibrate how confidently it answers (answer / answer cautiously /
    hand off). "none" means nothing cleared the relevance threshold.
    """
    if not chunks:
        return "none"
    best = min(c.distance for c in chunks)
    threshold = get_retrieval_threshold()
    if best <= threshold * HIGH_CONFIDENCE_RATIO:
        return "high"
    if best <= threshold * MEDIUM_CONFIDENCE_RATIO:
        return "medium"
    return "low"
