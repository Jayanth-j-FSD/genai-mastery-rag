"""Trace logging — save a full record of every request (needed for Weeks 4 & 5).

A "trace" is one line in a log file capturing the question, the
chunks we fetched, and the answer. Later weeks read this file to debug and measure.
Logging is best-effort: if it ever fails, it must NOT break the user's answer.
"""
import os
import json
from datetime import datetime

from app.config import settings


def log_trace(question, retrieved, answer, grounded):
    """Append one request as a JSON line. Never raises — logging is optional."""
    try:
        os.makedirs(os.path.dirname(settings.traces_path), exist_ok=True)
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "question": question,
            "retrieved": [
                {"source": c["source"], "score": c["score"], "text": c["text"]}
                for c in retrieved
            ],
            "answer": answer,
            "grounded": grounded,
            "config": {                          # which settings produced this answer
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
