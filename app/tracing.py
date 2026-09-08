"""Trace logging — save a full record of every request (needed for Weeks 4 & 5).

A "trace" is one line in a log file capturing the question, the
chunks we fetched, and the answer. Later weeks read this file to debug and measure.
Logging is best-effort: if it ever fails, it must NOT break the user's answer.

Week 4 additions: each retrieved chunk now also records WHY it was fetched (which
retriever found it, and at what rank), and the trace carries the retrieval mode and
a short id. That is what makes the inspection view and Week 5's sampling possible.
"""
import os
import json
import uuid
from datetime import datetime

from app.config import settings


def log_trace(question, retrieved, answer, grounded, retrieval_mode=None):
    """Append one request as a JSON line. Never raises — logging is optional."""
    try:
        os.makedirs(os.path.dirname(settings.traces_path), exist_ok=True)
        record = {
            "trace_id": uuid.uuid4().hex[:8],    # short handle, so Week 5 can cite a trace
            "ts": datetime.now().isoformat(timespec="seconds"),
            "question": question,
            "retrieved": [
                {
                    "source": c.get("source", "unknown"),
                    "score": c.get("score"),
                    # Why this chunk was fetched — the heart of the Week 4 inspection view.
                    "retrievers": c.get("retrievers", []),
                    "dense_rank": c.get("dense_rank"),
                    "keyword_rank": c.get("keyword_rank"),
                    "keyword_score": c.get("keyword_score"),
                    "rrf_score": c.get("rrf_score"),
                    "text": c.get("text", ""),
                }
                for c in (retrieved or [])
            ],
            "answer": answer,
            "grounded": grounded,
            "config": {                          # which settings produced this answer
                "retrieval_mode": retrieval_mode or settings.retrieval_mode,
                "chunk_size": settings.chunk_size,
                "chunk_overlap": settings.chunk_overlap,
                "top_k": settings.top_k,
                "embed_model": settings.embed_model,
                "llm_model": settings.llm_model,
            },
        }
        with open(settings.traces_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:                     # logging must never break answering
        print(f"  ! trace log failed (ignored): {exc}")


def read_traces(limit: int = None):
    """Read logged traces oldest-first, skipping any line that isn't valid JSON.

    Week 4's inspection view and Week 5's sampling both read the log through here, so
    the file format is understood in exactly one place. Each returned trace carries a
    1-based "line_no" so a specific trace can be cited and found again by hand.
    Returns [] when nothing has been logged yet.
    """
    path = settings.traces_path
    if not os.path.exists(path):
        return []

    traces = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                # A half-written last line (killed mid-append) must not break the reader.
                continue
            if isinstance(record, dict):
                record["line_no"] = line_no
                traces.append(record)

    # A negative or zero limit is treated as "no limit" rather than silently returning
    # nothing, which would look like an empty log.
    if limit and limit > 0:
        return traces[-limit:]
    return traces
