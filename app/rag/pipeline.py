"""The conductor — wires the six stages into the two actions the app performs.

In short:
  ingest()          run ONCE to read + index your documents
  answer(question)  run for EVERY question the user asks
"""
from app import llm
from app.config import settings
from app.rag import loader, chunker, embedder, keyword, store, retriever, generator
from app.tracing import log_trace


def require_index():
    """Raise a clear error if nothing is indexed.

    An empty index makes every question end in "I don't know", which is exactly what a correct
    refusal looks like, and makes every measurement read as a total retrieval failure. Better to
    stop and say what is wrong. Used by answer() and by the scripts that measure the app.
    """
    if store.count_chunks() == 0:
        raise RuntimeError("No documents are indexed yet. Run `python scripts/ingest.py` first.")


def ingest():
    """Read data/corpus/, split + embed everything, and save it to the index.
    Re-runnable: it replaces the index (only after the new vectors exist), so changing chunk size = re-ingest."""
    docs = loader.load_documents(settings.corpus_dir)
    if not docs:
        raise RuntimeError(
            f"No readable documents in {settings.corpus_dir!r}. "
            "Add .txt/.md/.pdf files there first."
        )
    chunks = chunker.chunk_documents(docs, settings.chunk_size, settings.chunk_overlap)
    if not chunks:
        raise RuntimeError("Documents were found but produced no text chunks.")

    # Embed FIRST and clear the index only once the vectors exist. Embedding is the step that
    # can fail (rate limit, missing model, Ctrl+C); if it did after the reset, the old index
    # would be gone and every later question would look like a polite "I don't know".
    embeddings = embedder.embed_texts([c["text"] for c in chunks])
    store.reset_collection()                       # start clean (supports re-ingest)
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

    require_index()                                # an empty index must not pass as a polite refusal

    chunks = retriever.retrieve_for_mode(question, settings.top_k, used_mode)
    llm.reset_last_model()                         # so the trace names the model of THIS answer, or None
    answer_text, sources, grounded = generator.generate_answer(question, chunks)
    # best-effort, never raises
    log_trace(question, chunks, answer_text, grounded, retrieval_mode=used_mode, model_served=llm.last_model())
    return {
        "answer": answer_text,
        "sources": [s.model_dump() for s in sources],
        "grounded": grounded,
        "retrieval_mode": used_mode,
    }
