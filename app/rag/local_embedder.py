"""A free, offline embedding model that runs on this machine (no API, no quota).

This loads a small sentence-embedding model (all-MiniLM-L6-v2) and
turns text into 384-number vectors right here on your computer. It is the free
alternative to a paid embeddings API. It needs two things on disk, downloaded once:
an ONNX model file and its tokenizer. The path is set by LOCAL_EMBED_DIR (see config).

It is deliberately dependency-light: onnxruntime (runs the model) and tokenizers
(splits text into the ids the model expects) — both already installed.
"""
import os

import numpy as np

from app.config import settings

_session = None
_tokenizer = None


def model_dir() -> str:
    """Where the model files live: LOCAL_EMBED_DIR if set, else ~/.cache/ai-task-minilm."""
    return settings.local_embed_dir or os.path.expanduser("~/.cache/ai-task-minilm")


def _load():
    """Load the ONNX session and tokenizer once, then reuse them."""
    global _session, _tokenizer
    if _session is None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        d = model_dir()
        model_path = os.path.join(d, "onnx", "model.onnx")
        tok_path = os.path.join(d, "tokenizer.json")
        if not os.path.exists(model_path) or not os.path.exists(tok_path):
            raise RuntimeError(
                f"Local embedding model not found under {d!r}. Expected onnx/model.onnx "
                "and tokenizer.json. Re-download it, or set EMBED_PROVIDER=openai."
            )
        _session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        _tokenizer = Tokenizer.from_file(tok_path)
        # Pad so a whole batch tokenizes to the same length (the model needs a matrix).
        _tokenizer.enable_padding()
        _tokenizer.enable_truncation(max_length=256)
    return _session, _tokenizer


def _mean_pool(token_vectors, attention_mask):
    """Average the per-token vectors into one vector per text, ignoring padding.

    all-MiniLM produces a vector per token; the sentence embedding is their mean
    over the real (non-padding) tokens. This matches how the model was trained.
    """
    mask = attention_mask[..., None].astype(np.float32)     # (batch, tokens, 1)
    summed = (token_vectors * mask).sum(axis=1)             # (batch, dim)
    counts = np.clip(mask.sum(axis=1), a_min=1e-9, a_max=None)
    return summed / counts


def embed(texts: list[str]) -> list[list[float]]:
    """Return one L2-normalised 384-dim vector per input text."""
    if not texts:
        return []
    session, tokenizer = _load()
    encs = tokenizer.encode_batch(texts)
    input_ids = np.array([e.ids for e in encs], dtype=np.int64)
    attention = np.array([e.attention_mask for e in encs], dtype=np.int64)
    token_type = np.zeros_like(input_ids)

    # Feed only the inputs this particular ONNX export declares.
    wanted = {i.name for i in session.get_inputs()}
    feed = {"input_ids": input_ids, "attention_mask": attention}
    if "token_type_ids" in wanted:
        feed["token_type_ids"] = token_type
    feed = {k: v for k, v in feed.items() if k in wanted}

    token_vectors = session.run(None, feed)[0]             # (batch, tokens, dim)
    pooled = _mean_pool(token_vectors, attention)          # (batch, dim)

    # Normalise so cosine similarity behaves (Chroma uses cosine).
    norms = np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9, None)
    return (pooled / norms).astype(np.float32).tolist()
