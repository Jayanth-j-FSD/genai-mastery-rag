"""Smart version of mentor check #4 — compare two chunk sizes automatically.

Instead of eyeballing, this re-indexes the documents at two chunk
sizes and reports, for each test question, whether the EXPECTED source document
was retrieved (and at what rank). That is a concrete way to "notice the difference".

Run:  python scripts/compare_chunks.py
Note: this uses the embeddings (to re-index) but not the answer model, so it's cheap
(free with EMBED_PROVIDER=local).
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings, BASE_DIR  # noqa: E402
from app.console import display_path, make_output_safe  # noqa: E402
from app.rag.pipeline import ingest      # noqa: E402
from app.rag.retriever import retrieve   # noqa: E402

# (question, expected source file) — keep in sync with tests/questions.md (questions 1-9).
CASES = [
    ("How many annual leave days does the Acme leave policy give full-time employees?", "Acme-Leave-Policy-2026.md"),
    ("How many unused leave days can be carried forward under the Acme leave policy?", "Acme-Leave-Policy-2026.md"),
    ("After how many days of service may an employee request remote work?", "Northstar-Remote-Work-Policy-2026.md"),
    ("What is the pension match?", "benefits.md"),
    ("What does error ERR-4032 mean?", "support-faq.md"),
    ("How often must passwords be rotated?", "security-policy.md"),
    ("Under the Acme employment terms, how many days of written notice must a permanent employee give?",
     "Acme-Employment-Terms-2026.md"),
    ("What are the four data classification levels?", "Nexora_Tech_Azure_Cloud_Data_Access_Policy.md"),
    ("What is the standard probation period?", "Synthetic_HR_Policy_RAG_Test_Dataset.md"),
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


def main():
    parser = argparse.ArgumentParser(description="Compare two chunk sizes over the checklist questions.")
    parser.add_argument("--save", action="store_true",
                        help="also write the numbers to docs/week3/chunk-experiment.md")
    args = parser.parse_args()
    make_output_safe()
    original = (settings.chunk_size, settings.chunk_overlap)   # remember .env setting
    runs, failure = [], None
    try:
        for cs, co in CONFIGS:
            runs.append((cs, co, *_run_config(cs, co)))
    except BaseException as exc:                # also Ctrl+C: the index must be put back in EVERY case
        failure = exc

    # Always put the index back to the .env configuration so the store isn't left changed,
    # and SAY if that fails: a silent failure would leave the index at 400/60 while every
    # later trace still logs chunk_size 800.
    settings.chunk_size, settings.chunk_overlap = original
    restore_error = None
    try:
        ingest()
    except Exception as exc:                    # noqa: BLE001 - report whatever went wrong
        restore_error = exc

    if restore_error:
        print(f"\nWARNING: the index could NOT be restored to chunk_size={original[0]}, "
              f"overlap={original[1]} ({type(restore_error).__name__}: {restore_error}).")
        print("It may still hold the last experiment's chunks. Run `python scripts/ingest.py` now.")
    if failure is not None:
        if not isinstance(failure, RuntimeError):
            raise failure                       # an interrupt or an unexpected error: surface it, after restoring
        print(f"Error: {failure}")
    if failure is not None or restore_error:
        return 1

    lines = []

    def emit(text=""):
        print(text)
        lines.append(text)

    emit("=== Chunk-size comparison (mentor check #4) ===")
    emit(f"settings: top_k={settings.top_k}, dense search = {settings.dense_search}, "
         f"embeddings = {settings.embed_provider}")
    for cs, co, stats, rows in runs:
        hits = sum(1 for r in rows if r[2])
        emit(f"\nchunk_size={cs}, overlap={co}  ({stats['chunks']} chunks total)  "
             f"expected source found: {hits}/{len(rows)}")
        for question, expected, hit, rank, top_score in rows:
            mark = f"OK rank {rank}" if hit else "MISS"
            emit(f"  [{mark:>9}] top={top_score:.3f}  {expected:<46} {question}")
    emit(f"\nIndex restored to your .env config (chunk_size={original[0]}, overlap={original[1]}).")
    emit("What changed between the two sizes, in words, is yours to write: see tests/questions.md.")

    if args.save:
        out_path = os.path.join(BASE_DIR, "docs", "week3", "chunk-experiment.md")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write("# Week 3 — chunk-size experiment output (generated)\n\n")
            handle.write(f"Generated {datetime.now().isoformat(timespec='seconds')} by "
                         "`python scripts/compare_chunks.py --save`. Numbers only: the written "
                         "observation (mentor check #4) is yours to write.\n\n")
            handle.write("```\n" + "\n".join(lines) + "\n```\n")
        print(f"\nSaved: {display_path(out_path, BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
