"""Pipeline stage 5 of 6 - RETRIEVE.

Embed the user's question the same way as the chunks, then ask
the store for the closest chunks. These become the ONLY facts the answer may use.
"""
from app.rag.embedder import embed_texts
from app.rag import store


def retrieve(question: str, top_k: int):
    """Return up to top_k chunks [{"text","source","score"}], closest first.
    Returns [] if nothing has been ingested yet."""
    question_vector = embed_texts([question])[0]
    result = store.query(question_vector, top_k)

    # Chroma nests results one level deep (one list per query); we sent one query,
    # so we take index [0]. The "or [[]]" guards against a missing/empty result.
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    chunks = []
    for text, meta, distance in zip(documents, metadatas, distances):
        chunks.append({
            "text": text,
            "source": (meta or {}).get("source", "unknown"),
            "score": round(1 - distance, 4),   # distance -> similarity (higher = closer)
        })
    return chunks
