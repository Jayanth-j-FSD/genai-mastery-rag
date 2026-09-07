"""Smart version of mentor check #4 — compare two chunk sizes automatically.

Instead of eyeballing, this re-indexes the documents at two chunk
sizes and reports, for each test question, whether the EXPECTED source document
was retrieved (and at what rank). That is a concrete way to "notice the difference".

Run:  python scripts/compare_chunks.py
Note: this uses the embeddings API (to re-index) but not the answer model, so it's cheap.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings          # noqa: E402
from app.rag.pipeline import ingest      # noqa: E402
from app.rag.retriever import retrieve   # noqa: E402

# (question, expected source file) — keep in sync with tests/questions.md.
CASES = [
    ("How many annual leave days do full-time employees get?", "annual-leave.md"),
    ("How many unused leave days can carry over to next year?", "annual-leave.md"),
    ("How many days a week can I work remotely?", "remote-work.md"),
    ("What is the pension match?", "benefits.md"),
    ("What does error ERR-4032 mean?", "support-faq.md"),
    ("How often must passwords be rotated?", "security-policy.md"),
    ("What is the daily meal limit while travelling?", "expenses.md"),
    ("What is the data retention on the Pro plan?", "support-faq.md"),
]

CONFIGS = [(800, 120), (400, 60)]   # (chunk_size, chunk_overlap) to compare


def _run_config(chunk_size, chunk_overlap):
    settings.chunk_size = chunk_size
    settings.chunk_overlap = chunk_overlap
    stats = ingest()                            # re-index at this chunk size
    rows = []
    for question, expected in CASES:
        chunks = retrieve(question, settings.top_k)
        sources = [c["source"] for c in chunks]
        top_score = chunks[0]["score"] if chunks else 0.0
        hit = expected in sources
        rank = sources.index(expected) + 1 if hit else None
        rows.append((question, expected, hit, rank, top_score))
    return stats, rows


if __name__ == "__main__":
    original = (settings.chunk_size, settings.chunk_overlap)   # remember .env setting
    runs = []
    try:
        for cs, co in CONFIGS:
            runs.append((cs, co, *_run_config(cs, co)))
    except RuntimeError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    finally:
        # Always restore the index to the .env config so the store isn't left changed.
        settings.chunk_size, settings.chunk_overlap = original
        try:
            ingest()
        except Exception:
            pass

    print("\n=== Chunk-size comparison (mentor check #4) ===")
    for cs, co, stats, rows in runs:
        hits = sum(1 for r in rows if r[2])
        print(f"\nchunk_size={cs}, overlap={co}  ({stats['chunks']} chunks total)  "
              f"expected source found: {hits}/{len(rows)}")
        for question, expected, hit, rank, top_score in rows:
            mark = f"OK rank {rank}" if hit else "MISS"
            print(f"  [{mark:>9}] top={top_score:.3f}  {expected:<18} {question}")
    print(f"\nIndex restored to your .env config (chunk_size={original[0]}, overlap={original[1]}).")
