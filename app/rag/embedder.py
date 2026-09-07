"""Pipeline stage 3 of 6 - EMBED.

An "embedding" turns text into a list of numbers (a vector) that
captures its meaning. Similar meanings get similar numbers, which is what lets
us search by meaning instead of by exact words.
"""
import os

from openai import OpenAI

from app.config import settings

_client = None       # created once, then reused
_BATCH = 100         # how many texts to send per API call


def _get_client() -> OpenAI:
    """Create the OpenAI client, with a clear error if the key is missing."""
    global _client
    if _client is None:
        key = settings.openai_api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "No OpenAI API key found. Copy .env.example to .env and set OPENAI_API_KEY."
            )
        _client = OpenAI(api_key=key)
    return _client


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return one vector per input text. The SAME model must embed both the
    document chunks and the questions, or the numbers won't be comparable."""
    if not texts:                     # nothing to embed -> no API call
        return []
    client = _get_client()
    vectors: list[list[float]] = []
    # Send in batches so a large corpus doesn't exceed the API's per-call limit.
    for start in range(0, len(texts), _BATCH):
        batch = texts[start:start + _BATCH]
        resp = client.embeddings.create(model=settings.embed_model, input=batch)
        vectors.extend(item.embedding for item in resp.data)
    return vectors
