"""The conductor — wires the six stages into the two actions the app performs.

In short:
  ingest()          run ONCE to read + index your documents
  answer(question)  run for EVERY question the user asks
"""
from app.config import settings
from app.rag import loader, chunker, embedder, keyword, store, retriever, generator
from app.tracing import log_trace


def ingest():
    """Read data/corpus/, split + embed everything, and save it to the index.
    Re-runnable: it clears the index first, so changing chunk size = re-ingest."""
    docs = loader.load_documents(settings.corpus_dir)
    if not docs:
        raise RuntimeError(
            f"No readable documents in {settings.corpus_dir!r}. "
            "Add .txt/.md/.pdf files there first."
        )
    chunks = chunker.chunk_documents(docs, settings.chunk_size, settings.chunk_overlap)
    if not chunks:
        raise RuntimeError("Documents were found but produced no text chunks.")

    store.reset_collection()                       # start clean (supports re-ingest)
    embeddings = embedder.embed_texts([c["text"] for c in chunks])
    store.add_chunks(chunks, embeddings)
    keyword.invalidate()                           # the keyword index is now stale (Week 4)

    # Count chunks per file so callers can SHOW how each document was split (check #4).
    per_source: dict[str, int] = {}
    for c in chunks:
        per_source[c["source"]] = per_source.get(c["source"], 0) + 1
    return {"documents": len(docs), "chunks": len(chunks), "per_source": per_source}


def answer(question: str, mode: str = None):
    """Answer one question from the indexed documents and log the trace.
    Returns {"answer", "sources": [{document, score}], "grounded", "retrieval_mode"}.

    `mode` forces a retrieval strategy ("dense" or "hybrid") for this one call; leave
    it None to use `settings.retrieval_mode`. Week 4 added both the argument and the
    "retrieval_mode" key in the result — the original three keys are unchanged."""
    used_mode = (mode or settings.retrieval_mode or "dense").strip().lower()

    question = (question or "").strip()
    if not question:                               # empty question -> don't call the API
        return {
            "answer": "Please ask a question.",
            "sources": [],
            "grounded": False,
            "retrieval_mode": used_mode,
        }

    chunks = retriever.retrieve_for_mode(question, settings.top_k, used_mode)
    answer_text, sources, grounded = generator.generate_answer(question, chunks)
    # best-effort, never raises
    log_trace(question, chunks, answer_text, grounded, retrieval_mode=used_mode)
    return {
        "answer": answer_text,
        "sources": [s.model_dump() for s in sources],
        "grounded": grounded,
        "retrieval_mode": used_mode,
    }
