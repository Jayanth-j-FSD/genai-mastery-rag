"""Shared helpers for the offline unit tests.

These tests must never touch your real index, the network, or the free-tier
quota. So they get (1) a throwaway Chroma folder and (2) a fake embedder that turns words
into numbers without any model. Texts that share words land close together, which is all a
retrieval test needs.
"""
import contextlib
import hashlib
import os
import re
import sys
import tempfile
from unittest import mock

# Chroma phones home with anonymous usage stats by default; a test run should send nothing.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import settings          # noqa: E402
from app.rag import keyword, store       # noqa: E402

DIM = 64


def fake_embed(texts):
    """One deterministic unit vector per text, built from hashed words (no model needed)."""
    vectors = []
    for text in texts:
        vector = [0.0] * DIM
        for word in re.findall(r"[a-z0-9]+", (text or "").lower()):
            vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = sum(x * x for x in vector) ** 0.5 or 1.0
        vectors.append([x / norm for x in vector])
    return vectors


@contextlib.contextmanager
def isolated_index(**setting_overrides):
    """Point the app at an empty temporary index and traces file, then put everything back.

    Extra keyword arguments temporarily override other settings, e.g. dense_search="ann".
    Yields the temporary folder so a test can put files in it.
    """
    names = ["chroma_dir", "collection", "traces_path", *setting_overrides]
    saved = {name: getattr(settings, name) for name in names}
    # ignore_cleanup_errors: on Windows Chroma may still hold its database file open.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        settings.chroma_dir = os.path.join(tmp, "chroma")
        settings.collection = "unit_test_docs"
        settings.traces_path = os.path.join(tmp, "traces", "traces.jsonl")
        for name, value in setting_overrides.items():
            setattr(settings, name, value)
        store._client = None              # forget any client opened on the real folder
        keyword.invalidate()              # the keyword cache is keyed by chunk count only
        try:
            yield tmp
        finally:
            store._client = None
            keyword.invalidate()
            for name, value in saved.items():
                setattr(settings, name, value)


def build_index(chunks):
    """Store chunks [{chunk_id, text, source}] in the current index using the fake embedder."""
    store.reset_collection()
    store.add_chunks(chunks, fake_embed([c["text"] for c in chunks]))
    keyword.invalidate()


def patched_embeddings():
    """Make every part of the app use the fake embedder instead of a real model or API."""
    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch("app.rag.retriever.embed_texts", fake_embed))
    stack.enter_context(mock.patch("app.rag.embedder.embed_texts", fake_embed))
    return stack


def chunk(chunk_id, text, source=None):
    """Shorthand for a chunk dict; the source defaults to the part of the id before '#'."""
    return {"chunk_id": chunk_id, "text": text, "source": source or chunk_id.split("#")[0]}


def fake_response(content="ok", tool_calls=None, prompt_tokens=7, completion_tokens=3):
    """Look like an OpenAI chat response, as far as this app reads one."""
    from types import SimpleNamespace as NS
    message = NS(content=content, tool_calls=tool_calls)
    return NS(
        choices=[NS(message=message, finish_reason="tool_calls" if tool_calls else "stop")],
        usage=NS(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )
