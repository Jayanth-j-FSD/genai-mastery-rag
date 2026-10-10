"""Pipeline stage 3 of 6 - EMBED.

An "embedding" turns text into a list of numbers (a vector) that
captures its meaning. Similar meanings get similar numbers, which is what lets
us search by meaning instead of by exact words.

Two ways to make those numbers, chosen by settings.embed_provider:
  "openai"  send the text to the embed_model API (needs a key; may have a quota)
  "local"   run a small model on THIS machine: free, unlimited, offline

Whichever is used, the SAME model must embed both the document chunks and the
questions, or the numbers won't be comparable. Re-ingest after switching.

Free API tiers cap requests per minute (Gemini's free tier counts each text as
one request). settings.embed_rpm throttles the API path to stay under that: it
sends small batches and pauses when the current minute's budget is used up.
"""
import os
import time

from openai import OpenAI, RateLimitError

from app.config import settings

_client = None       # OpenAI client, created once then reused
_local = None        # local embedding function, created once then reused

# Keep API batches small: a very large single call can hang on some compatible
# endpoints, and small calls give visible progress. Each text is one request.
_API_BATCH = 10


def _get_client() -> OpenAI:
    """Create the OpenAI client, with a clear error if the key is missing."""
    global _client
    if _client is None:
        key = settings.openai_api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "No OpenAI API key found. Copy .env.example to .env and set OPENAI_API_KEY."
            )
        # base_url lets us use an OpenAI-compatible provider (e.g. Gemini) for
        # free. Blank = real OpenAI, so default behaviour is unchanged.
        base_url = settings.openai_base_url or os.environ.get("OPENAI_BASE_URL") or None
        _client = OpenAI(api_key=key, base_url=base_url)
    return _client


def _get_local():
    """Load (once) a small embedding model that runs on this machine.

    Uses the ONNX model that ships with chromadb, so there is nothing extra to
    install. It downloads ~80MB the first time, then runs offline with no quota.
    """
    global _local
    if _local is None:
        from chromadb.utils import embedding_functions as ef
        _local = ef.ONNXMiniLM_L6_V2()
    return _local


def _create_with_retry(client, batch, max_retries: int = 5):
    """Call the embeddings API, waiting and retrying if the rate limit is hit.

    A free tier can still return 429 if a previous run used this minute's budget.
    Rather than crash a long ingest, back off and retry a few times.
    """
    for attempt in range(1, max_retries + 1):
        try:
            return client.embeddings.create(model=settings.embed_model, input=batch)
        except RateLimitError:
            if attempt == max_retries:
                raise
            wait = 30 * attempt
            print(f"  rate limited; waiting {wait}s then retrying "
                  f"(attempt {attempt}/{max_retries})...", flush=True)
            time.sleep(wait)


def _embed_api(texts: list[str]) -> list[list[float]]:
    """Embed via the API, throttled to settings.embed_rpm requests per minute.

    A simple rolling-window limiter: it counts how many texts (= requests) have
    gone out in the current 60-second window and, when the next batch would cross
    the limit, waits for the window to reset before continuing.
    """
    client = _get_client()
    rpm = settings.embed_rpm if settings.embed_rpm and settings.embed_rpm > 0 else 0

    vectors: list[list[float]] = []
    window_start = time.monotonic()
    sent_this_window = 0
    total = len(texts)

    for start in range(0, total, _API_BATCH):
        batch = texts[start:start + _API_BATCH]

        if rpm:
            # If this batch would exceed the minute's budget, wait out the window.
            if sent_this_window + len(batch) > rpm:
                elapsed = time.monotonic() - window_start
                wait = max(0.0, 60.0 - elapsed) + 1.0
                print(f"  embedded {start}/{total}; free-tier limit reached, "
                      f"pausing {wait:.0f}s...", flush=True)
                time.sleep(wait)
                window_start = time.monotonic()
                sent_this_window = 0

        resp = _create_with_retry(client, batch)
        vectors.extend(item.embedding for item in resp.data)
        sent_this_window += len(batch)

    return vectors


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return one vector per input text. The SAME model must embed both the
    document chunks and the questions, or the numbers won't be comparable."""
    if not texts:                     # nothing to embed -> no work
        return []
    if settings.embed_provider == "local":
        # Runs on this machine: free, unlimited, offline. No batch limit to manage.
        from app.rag import local_embedder
        return local_embedder.embed(texts)
    return _embed_api(texts)
