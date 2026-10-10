"""Pipeline stage 4 of 6 - STORE (the vector database).

Chroma saves all the chunk vectors on disk and can quickly find
the ones closest in meaning to a question. "cosine" is how we measure closeness.
"""
import chromadb
import numpy as np

from app.config import settings

_client = None


def _get_client():
    """Open (once) the on-disk Chroma database in data/chroma/."""
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=settings.chroma_dir)
    return _client


def get_collection():
    """Return our collection (like a table), creating it if it doesn't exist."""
    return _get_client().get_or_create_collection(
        name=settings.collection,
        metadata={"hnsw:space": "cosine"},   # measure closeness by cosine similarity
    )


def reset_collection():
    """Delete + recreate the collection so re-ingesting starts clean (no duplicate chunks)."""
    client = _get_client()
    try:
        client.delete_collection(settings.collection)
    except Exception:
        pass   # it may not exist yet on the first run — that's fine
    return get_collection()


def add_chunks(chunks, embeddings):
    """Save chunks + their vectors + source names into the collection."""
    if not chunks:            # nothing to add
        return
    get_collection().add(
        ids=[c["chunk_id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        embeddings=embeddings,
        metadatas=[{"source": c["source"]} for c in chunks],
    )


def query(embedding, top_k: int):
    """Return the nearest chunks to one question vector, in Chroma's result shape.

    settings.dense_search picks how they are found:
      "exact"  compare the question with EVERY stored vector. Always the true nearest chunks,
               in the same order on every run. For a few thousand chunks that takes milliseconds.
      "ann"    Chroma's approximate HNSW index. On this corpus it returned the wrong top chunk
               for many questions (136 identical chunks trap its graph search), and differently
               on each run. Kept so the problem can be reproduced: scripts/compare_ann_exact.py.
    """
    if settings.dense_search == "ann":
        return get_collection().query(query_embeddings=[embedding], n_results=top_k)
    return _query_exact(embedding, top_k)


def _query_exact(embedding, top_k: int):
    """Brute-force nearest neighbours: cosine distance to every stored chunk, then sort.

    Costs one pass over all vectors per question, so it suits a corpus of up to a few tens of
    thousands of chunks. Beyond that, an approximate index is the right tool.
    """
    empty = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    if top_k <= 0:
        return empty
    stored = get_collection().get(include=["embeddings", "documents", "metadatas"])
    ids = stored.get("ids") or []
    vectors = stored.get("embeddings")
    if not ids or vectors is None or len(vectors) == 0:     # nothing ingested yet
        return empty

    matrix = np.asarray(vectors, dtype=np.float64)
    question = np.asarray(embedding, dtype=np.float64)
    if matrix.shape[1] != question.shape[0]:
        raise RuntimeError(
            f"The question vector has {question.shape[0]} numbers but the index stores "
            f"{matrix.shape[1]}. The index was built with a different embedding model: "
            "re-ingest it with `python scripts/ingest.py`."
        )

    # Cosine distance = 1 - cosine similarity. Dividing by both lengths means vectors that are
    # not exactly unit length still compare by angle only. A zero vector has no direction: distance 1.
    lengths = np.linalg.norm(matrix, axis=1) * np.linalg.norm(question)
    similarity = np.divide(matrix @ question, lengths, out=np.zeros(len(ids)), where=lengths > 0)
    distance = 1.0 - similarity

    # Nearest first. Identical chunks tie on distance, so break ties by id: the same question
    # then returns the same chunks in the same order on every run (rounding hides float noise).
    order = np.lexsort((np.asarray(ids), np.round(distance, 6)))[:top_k]
    documents = stored.get("documents") or []
    metadatas = stored.get("metadatas") or []
    return {
        "ids": [[ids[i] for i in order]],
        "documents": [[documents[i] for i in order]],
        "metadatas": [[metadatas[i] for i in order]],
        "distances": [[float(distance[i]) for i in order]],
    }


# --- Week 4 additions: read the chunks back out, for keyword search and inspection ---

def count_chunks() -> int:
    """How many chunks are currently indexed. Used to detect a stale keyword index."""
    try:
        return get_collection().count()
    except Exception:
        return 0                     # a missing/unreadable collection counts as empty


def get_all_chunks():
    """Return every stored chunk as {"chunk_id", "text", "source"}.

    Keyword search (BM25) needs the raw text of all chunks, which the vector store
    already holds — so there is no second copy of the corpus to keep in sync.
    """
    result = get_collection().get(include=["documents", "metadatas"])
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []

    chunks = []
    for i, chunk_id in enumerate(ids):
        # Index defensively: a malformed row should be skipped, not crash the search.
        text = documents[i] if i < len(documents) else None
        meta = metadatas[i] if i < len(metadatas) else None
        if not text:
            continue
        chunks.append({
            "chunk_id": chunk_id,
            "text": text,
            "source": (meta or {}).get("source", "unknown"),
        })
    return chunks


def get_embeddings(chunk_ids):
    """Return {chunk_id: vector} for the given ids, so a cosine score can be computed
    for a chunk that keyword search found but vector search did not return."""
    if not chunk_ids:
        return {}
    result = get_collection().get(ids=list(chunk_ids), include=["embeddings"])
    ids = result.get("ids") or []
    embeddings = result.get("embeddings")
    if embeddings is None:                 # explicit: numpy arrays are falsy when empty
        return {}

    vectors = {}
    for i, chunk_id in enumerate(ids):
        if i >= len(embeddings):
            continue
        vector = embeddings[i]
        if vector is None:
            continue
        # Chroma may hand back numpy arrays; normalise to plain floats.
        vectors[chunk_id] = [float(value) for value in vector]
    return vectors
