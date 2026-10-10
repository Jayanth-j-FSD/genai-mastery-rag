"""Evidence for the exact-search fix: how often does Chroma's approximate search get it wrong?

Chroma finds "the nearest chunks" with an approximate index (HNSW) that walks a
graph of vectors instead of checking all of them. That is fast on millions of chunks, but it can
miss. On this corpus one chunk is repeated 136 times and another 108 times, and those identical
vectors make the graph walk unreliable. This script asks every question twice, once with the
approximate index and once with an exact search over the same stored vectors, and counts how
often the two disagree.

Run it more than once. The approximate index is rebuilt in memory each time the program starts,
in a slightly different order, so each run is a new draw and the numbers move:

    python scripts/compare_ann_exact.py
    python scripts/compare_ann_exact.py --k 4 --show 5

Only the embedding of the questions is needed (free with EMBED_PROVIDER=local); the answer model
is never called.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings, BASE_DIR           # noqa: E402
from app.console import display_path, make_output_safe  # noqa: E402
from app.rag import store                           # noqa: E402
from app.rag.embedder import embed_texts            # noqa: E402

DEFAULT_QUESTIONS = os.path.join(BASE_DIR, "tests", "trace_questions.txt")


def load_questions(path):
    """One question per line; blank lines and # comments are skipped."""
    with open(path, encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip() and not line.lstrip().startswith("#")]


def _search(vector, k, mode):
    """Run the store's dense search in one mode ("exact" or "ann"), then put the setting back."""
    original = settings.dense_search
    settings.dense_search = mode
    try:
        return store.query(vector, k)
    finally:
        settings.dense_search = original


def main():
    parser = argparse.ArgumentParser(description="Compare approximate and exact dense search.")
    parser.add_argument("--file", default=DEFAULT_QUESTIONS, help="questions to ask, one per line")
    parser.add_argument("--k", type=int, default=settings.top_k, help="how many chunks to compare")
    parser.add_argument("--show", type=int, default=3, help="how many disagreements to print in detail")
    args = parser.parse_args()
    make_output_safe()

    if args.k < 1:
        print(f"Error: --k must be 1 or greater, got {args.k}.")
        return 1
    if store.count_chunks() == 0:
        print("Error: nothing is indexed yet. Run `python scripts/ingest.py` first.")
        return 1
    questions = load_questions(args.file)
    if not questions:
        print(f"No questions found in {display_path(args.file, BASE_DIR)}.")
        return 1

    vectors = embed_texts(questions)
    rows = []
    for question, vector in zip(questions, vectors):
        approximate = _search(vector, args.k, "ann")
        exact = _search(vector, args.k, "exact")
        rows.append({
            "question": question,
            "ann_ids": approximate["ids"][0], "exact_ids": exact["ids"][0],
            "ann_scores": [round(1 - d, 4) for d in approximate["distances"][0]],
            "exact_scores": [round(1 - d, 4) for d in exact["distances"][0]],
        })

    total = len(rows)
    top1_differs = [r for r in rows if r["ann_ids"][:1] != r["exact_ids"][:1]]
    set_differs = [r for r in rows if set(r["ann_ids"]) != set(r["exact_ids"])]
    overlap = sum(len(set(r["ann_ids"]) & set(r["exact_ids"])) / max(len(r["exact_ids"]), 1) for r in rows) / total

    print(f"=== approximate (HNSW) vs exact dense search, k={args.k}, {total} questions ===")
    print(f"index: {store.count_chunks()} chunks, embeddings: {settings.embed_provider}")
    print(f"top-1 chunk differs from exact : {len(top1_differs)}/{total}  ({len(top1_differs) / total:.0%})")
    print(f"top-{args.k} set differs from exact : {len(set_differs)}/{total}  ({len(set_differs) / total:.0%})")
    print(f"mean overlap@{args.k}                : {overlap:.3f}   (1.000 means identical)")
    for row in top1_differs[:max(args.show, 0)]:
        print(f"\n  Q: {row['question']}")
        print(f"     exact search : {row['exact_ids'][:2]}  scores {row['exact_scores'][:2]}")
        print(f"     approximate  : {row['ann_ids'][:2]}  scores {row['ann_scores'][:2]}")
    print("\nThis run is one draw: the approximate index is rebuilt in a different order each "
          "time the program starts, so run it again and the counts will move. Exact search never does.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
