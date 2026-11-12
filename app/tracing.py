"""Trace logging — save a full record of every request (needed for Weeks 4 & 5).

A "trace" is one line in a log file capturing the question, the
chunks we fetched, and the answer. Later weeks read this file to debug and measure.
Logging is best-effort: if it ever fails, it must NOT break the user's answer.

Week 4 additions: each retrieved chunk now also records WHY it was fetched (which
retriever found it, and at what rank), and the trace carries the retrieval mode and
a short id. That is what makes the inspection view and Week 5's sampling possible.

Week 11 additions, all optional keys on the same line (the older keys and their meanings are unchanged, and a line written
before Week 11 is still a complete record): the request id, when it started, the spans (one per step, with how long it
took and what it cost), the tokens, the sources it cited and why it refused. A request that FAILED has no answer to log; it
goes to errors.jsonl beside this file as a short record (what failed, when, the steps it had finished), never its text.
The file is safe for several threads and, with an OS lock on a side file, for several processes at once.
"""
import contextlib
import json
import os
import threading
import time
import uuid
from datetime import datetime

from app import observability
from app.config import settings

try:                                   # an OS lock on a side file, so two PROCESSES cannot write into each other
    import msvcrt
except ImportError:                    # not Windows
    msvcrt = None
try:
    import fcntl
except ImportError:                    # Windows
    fcntl = None

_append_lock = threading.Lock()
_dropped = {"records": 0}


class LogBusy(Exception):
    """Another process held the log's lock for longer than we were willing to wait."""


def errors_path():
    """Where failed requests are logged: beside the traces, so a test that points the traces somewhere else moves this too."""
    return os.path.join(os.path.dirname(settings.traces_path), "errors.jsonl")


def dropped_records():
    """How many lines were not written because another process held the lock too long (this process, since it started)."""
    return _dropped["records"]


@contextlib.contextmanager
def _process_lock(path, timeout):
    """Hold an OS lock on `path` (one byte of a side file) while the block runs; LogBusy if it cannot be had within `timeout`."""
    if msvcrt is None and fcntl is None:
        yield
        return
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if msvcrt is not None:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise LogBusy(f"{os.path.basename(path)} is held by another process")
                time.sleep(0.01)
        try:
            yield
        finally:
            try:
                if msvcrt is not None:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        os.close(descriptor)


def append_line(path, line, timeout=2.0):
    """Append one line to a log. Safe for threads (a lock) and processes (an OS lock on `path + ".lock"`), and if an earlier
    write was cut off before its newline, the new line starts on a fresh line instead of being glued to the torn one."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = line.encode("utf-8") + b"\n"
    with _append_lock, _process_lock(path + ".lock", timeout):
        glue = b""
        if os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path, "rb") as handle:
                handle.seek(-1, os.SEEK_END)
                glue = b"" if handle.read(1) == b"\n" else b"\n"
        with open(path, "ab") as handle:
            handle.write(glue + data)


def _base_record(question, retrieved, answer, grounded, retrieval_mode=None, model_served=None):
    """The record exactly as Weeks 3 to 5 wrote it. The drill generator builds its lines from this too, so they cannot drift."""
    return {
        "trace_id": uuid.uuid4().hex[:8],    # short handle, so Week 5 can cite a trace
        "ts": datetime.now().isoformat(timespec="seconds"),
        "question": question,
        "retrieved": [
            {
                "source": c.get("source", "unknown"),
                "score": c.get("score"),
                # Why this chunk was fetched: the heart of the Week 4 inspection view.
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
            # What REALLY ran, so a trace can be replayed later. embed_model above is only
            # a setting: with embed_provider "local" the vectors came from the local model.
            # And a name like "gemini-flash-latest" is an alias that moves over time.
            "embed_provider": settings.embed_provider,
            "dense_search": settings.dense_search,
            "llm_model_served": model_served,       # None when no model call was needed (a refusal)
        },
    }


def _dump(record):
    """One JSON line. A lone surrogate (half of an emoji, when a reply was cut in the middle of one) cannot be written as UTF-8, so a record that holds one is written
    with ASCII escapes, which JSON can carry; the line is kept, not dropped."""
    line = json.dumps(record, ensure_ascii=False)
    try:
        line.encode("utf-8")
    except UnicodeEncodeError:
        line = json.dumps(record, ensure_ascii=True)
    return line


def log_trace(question, retrieved, answer, grounded, retrieval_mode=None, model_served=None):
    """Append one request as a JSON line. Never raises: logging is optional.

    When the request has a log (app/observability.py), its id, spans and notes join the line as extra keys, and the trace
    id is the first 8 hex digits of the request id."""
    try:
        record = _base_record(question, retrieved, answer, grounded, retrieval_mode, model_served)
        request = observability.current()
        if request is not None:
            record["trace_id"] = request.trace_id
            record.update(observability.guarded("record_extras", observability.record_extras, request,
                                                status="ok" if grounded else "refused", default={}))
        append_line(settings.traces_path, _dump(record))
    except LogBusy as exc:
        _dropped["records"] += 1
        print(f"  ! trace log busy, one record dropped (counted): {exc}")
    except Exception as exc:                     # logging must never break answering
        print(f"  ! trace log failed (ignored): {exc}")


def status_for(exc):
    """The HTTP status the API answers this failure with (app/main.py `_run` does the real mapping), or None when it maps none."""
    import openai
    from app import llm
    if isinstance(exc, llm.QuotaExhausted):
        return 429
    if isinstance(exc, RuntimeError):
        return 400
    if isinstance(exc, openai.RateLimitError):
        return 429
    if isinstance(exc, (openai.APIStatusError, openai.APIConnectionError)):
        return 502
    return None


def log_error(request, exc, question=""):
    """Record a request that failed: its id, when, how it arrived, the steps it had finished, the kind of failure and its HTTP
    status. NEVER the exception's message (a provider error can echo request details) and never the question: only its length
    and a short hash, so a known question can be matched without the log holding it. Never raises."""
    try:
        if request is None:
            return
        record = observability.snapshot(request)
        record.update(trace_id=request.trace_id, ts=datetime.now().isoformat(timespec="seconds"), error_class=type(exc).__name__,
                      http_status=status_for(exc), question_chars=len(question or ""), question_sha=observability.sha12(question or ""))
        append_line(errors_path(), _dump(record))
    except LogBusy as busy:
        _dropped["records"] += 1
        print(f"  ! error log busy, one record dropped (counted): {busy}")
    except Exception as failure:
        print(f"  ! error log failed (ignored): {failure}")


def _read_jsonl(path, limit):
    """The records of a JSON-lines file, oldest first, skipping lines that are not valid JSON objects, each with its 1-based line_no."""
    if not os.path.exists(path):
        return []

    records = []
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
                records.append(record)

    # A negative or zero limit is treated as "no limit" rather than silently returning
    # nothing, which would look like an empty log.
    if limit and limit > 0:
        return records[-limit:]
    return records


def read_traces(limit: int = None, path: str = None):
    """Read logged traces oldest-first, skipping any line that isn't valid JSON.

    Week 4's inspection view and Week 5's sampling both read the log through here, so
    the file format is understood in exactly one place. Each returned trace carries a
    1-based "line_no" so a specific trace can be cited and found again by hand.
    Returns [] when nothing has been logged yet. `path` (Week 11) reads another log of
    the same format, such as a measurement's or the drill's, with the same reader.
    """
    return _read_jsonl(path or settings.traces_path, limit)


def read_errors(limit: int = None, path: str = None):
    """The failed requests of errors.jsonl, oldest first, read the same way."""
    return _read_jsonl(path or errors_path(), limit)
