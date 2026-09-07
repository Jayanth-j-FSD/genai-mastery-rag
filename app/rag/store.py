"""Pipeline stage 4 of 6 - STORE (the vector database).

Chroma saves all the chunk vectors on disk and can quickly find
the ones closest in meaning to a question. "cosine" is how we measure closeness.
"""
import chromadb

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
    """Return Chroma's raw nearest-neighbour result for one question vector."""
    return get_collection().query(query_embeddings=[embedding], n_results=top_k)
