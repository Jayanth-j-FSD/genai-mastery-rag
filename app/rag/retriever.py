"""Pipeline stage 5 of 6 - RETRIEVE.

Embed the user's question the same way as the chunks, then ask
the store for the closest chunks. These become the ONLY facts the answer may use.

Week 4 adds a second way to search. There are now two strategies:
  dense   embed the question, take the nearest chunks by meaning   (Week 3, unchanged)
  hybrid  do that AND a keyword search, then merge the two rankings (Week 4's change)

`retrieve()` below is still exactly the Week 3 dense search and still means what its
docstring says. The hybrid path is a separate function, and `retrieve_for_mode()`
picks between them, so switching strategies is a config change and the before/after
comparison is a fair one.
"""
import math

from app.config import settings
from app.rag.embedder import embed_texts
from app.rag import fusion, keyword, store


def _cosine(left, right) -> float:
    """Cosine similarity between two vectors: 1.0 = identical direction, 0.0 = unrelated."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:       # a zero vector has no direction
        return 0.0
    return dot / (left_norm * right_norm)


def _dense_search(question_vector, top_k: int):
    """Nearest chunks by meaning. Returns [{"chunk_id","text","source","score",...}]."""
    result = store.query(question_vector, top_k)

    # Chroma nests results one level deep (one list per query); we sent one query,
    # so we take index [0]. The "or [[]]" guards against a missing/empty result.
    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    chunks = []
    for position, (text, meta, distance) in enumerate(zip(documents, metadatas, distances), start=1):
        chunks.append({
            # chunk_id lets Week 4 match this chunk against the keyword search's hit.
            "chunk_id": ids[position - 1] if position - 1 < len(ids) else "",
            "text": text,
            "source": (meta or {}).get("source", "unknown"),
            "score": round(1 - distance, 4),   # distance -> similarity (higher = closer)
            "score_kind": "cosine",
            "dense_rank": position,
            "keyword_rank": None,
            "keyword_score": None,
            "retrievers": ["dense"],
        })
    return chunks


def retrieve(question: str, top_k: int):
    """Return up to top_k chunks [{"text","source","score"}], closest first.
    Returns [] if nothing has been ingested yet.

    This is the dense (meaning-only) search, unchanged from Week 3 — `score` is a
    cosine similarity. Week 4 also attaches `chunk_id`, `score_kind`, `dense_rank`,
    `keyword_rank`, `keyword_score` and `retrievers`; those are extra keys for the
    inspection view and do not change the meaning of the three original ones.
    """
    # An empty question would otherwise be sent to the embeddings API, which rejects it.
    if top_k <= 0 or not (question or "").strip():
        return []
    question_vector = embed_texts([question])[0]
    return _dense_search(question_vector, top_k)


def retrieve_hybrid(question: str, top_k: int):
    """Week 4: dense search + keyword search, merged with Reciprocal Rank Fusion.

    Same return shape as `retrieve()`. `score` is still a cosine similarity, so the
    `min_relevance` floor and the reported source scores keep the meaning they had in
    Week 3 — a chunk that only keyword search found gets its cosine computed here
    rather than being reported with an incomparable BM25 number.
    """
    if top_k <= 0 or not (question or "").strip():
        return []

    # Ask each retriever for a wider pool than we need, so fusion has room to reorder.
    candidate_count = max(settings.hybrid_candidates, top_k)

    question_vector = embed_texts([question])[0]
    dense_hits = _dense_search(question_vector, candidate_count)
    keyword_hits = keyword.search(question, candidate_count)

    # Index both result sets by chunk_id so the same chunk found twice is one entry.
    by_id: dict[str, dict] = {}
    for hit in dense_hits:
        if hit["chunk_id"]:
            by_id[hit["chunk_id"]] = dict(hit)
    for position, hit in enumerate(keyword_hits, start=1):
        chunk_id = hit.get("chunk_id") or ""
        if not chunk_id:
            continue
        existing = by_id.get(chunk_id)
        if existing is None:
            # Found by keyword search only; its cosine score is filled in below.
            by_id[chunk_id] = {
                "chunk_id": chunk_id,
                "text": hit["text"],
                "source": hit["source"],
                "score": None,
                "score_kind": "cosine",
                "dense_rank": None,
                "keyword_rank": position,
                "keyword_score": hit["keyword_score"],
                "retrievers": ["keyword"],
            }
        else:
            existing["keyword_rank"] = position
            existing["keyword_score"] = hit["keyword_score"]
            existing["retrievers"] = ["dense", "keyword"]

    if not by_id:
        return []

    ranked = fusion.fuse(
        {
            "dense": [hit["chunk_id"] for hit in dense_hits if hit["chunk_id"]],
            "keyword": [hit["chunk_id"] for hit in keyword_hits if hit.get("chunk_id")],
        },
        settings.rrf_k,
    )

    # Keep only what we were asked for, in fused order.
    selected = []
    for entry in ranked[:top_k]:
        chunk = by_id.get(entry["key"])
        if chunk is None:
            continue
        chunk["rrf_score"] = entry["rrf_score"]
        selected.append(chunk)

    # Give every keyword-only chunk a real cosine score, so all scores stay comparable.
    missing_scores = [c["chunk_id"] for c in selected if c["score"] is None]
    if missing_scores:
        try:
            vectors = store.get_embeddings(missing_scores)
        except Exception as exc:
            # A score is presentation detail — never fail an answer over it.
            print(f"  ! could not read embeddings for scoring (ignored): {exc}")
            vectors = {}
        for chunk in selected:
            if chunk["score"] is None:
                vector = vectors.get(chunk["chunk_id"])
                chunk["score"] = round(_cosine(question_vector, vector), 4) if vector else 0.0

    return selected


def retrieve_for_mode(question: str, top_k: int, mode: str = None):
    """Retrieve using the configured strategy — "dense" (Week 3) or "hybrid" (Week 4).

    Pass `mode` explicitly to force one strategy, which is how the evaluation script
    measures both without editing any config.
    """
    chosen = (mode or settings.retrieval_mode or "dense").strip().lower()
    if chosen == "hybrid":
        return retrieve_hybrid(question, top_k)
    if chosen == "dense":
        return retrieve(question, top_k)
    raise ValueError(f"Unknown retrieval mode {chosen!r}. Use 'dense' or 'hybrid'.")
