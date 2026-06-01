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
