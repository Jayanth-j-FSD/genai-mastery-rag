"""Evidence for the exact-search fix: how often does Chroma's approximate search get it wrong?

Chroma finds "the nearest chunks" with an approximate index (HNSW) that walks a
graph of vectors instead of checking all of them. That is fast on millions of chunks, but it can
miss. On this corpus one chunk is repeated 136 times and another 108 times (264 of 432 chunks are
exact copies), and the approximate search then returned a different top chunk from the true one for a
large share of questions. This script asks every question twice, once with the approximate index and
once with an exact search over the same stored vectors, and counts how often the two disagree.

The disagreement changes from run to run: a different run, a different count. That was observed
directly (see the numbers saved by --save). The likely cause is that the index is rebuilt in memory
each time the program starts, but that mechanism was not verified: the fix does not depend on it,
because exact search has no such behaviour.

Run it more than once; every run is a new program start:

    python scripts/compare_ann_exact.py
    python scripts/compare_ann_exact.py --show 5
    python scripts/compare_ann_exact.py --save                  # append this run to docs/hardening/ann-vs-exact.md
    python scripts/compare_ann_exact.py --ef-search 500 --save  # a TUNED approximate index (a throwaway copy)

`--ef-search N` builds a temporary copy of the index with a larger search width, which is the usual
first thing to try when an approximate index misses. It is a throwaway: your real index is not touched.

Only the embedding of the questions is needed (free with EMBED_PROVIDER=local); the answer model is
never called.
"""
import argparse
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings, BASE_DIR           # noqa: E402
from app.console import display_path, make_output_safe  # noqa: E402
from app.rag import store                           # noqa: E402
from app.rag.embedder import embed_texts            # noqa: E402

DEFAULT_QUESTIONS = os.path.join(BASE_DIR, "tests", "trace_questions.txt")
SAVE_PATH = os.path.join(BASE_DIR, "docs", "hardening", "ann-vs-exact.md")


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


def _tuned_collection(ef_search, directory):
    """A throwaway copy of every stored vector in a Chroma folder whose HNSW search width is `ef_search`."""
    import chromadb

    stored = store.get_collection().get(include=["embeddings", "documents", "metadatas"])
    collection = chromadb.PersistentClient(path=directory).create_collection(
        "tuned", configuration={"hnsw": {"space": "cosine", "ef_search": ef_search}})
    collection.add(ids=stored["ids"], documents=stored["documents"], metadatas=stored["metadatas"],
                   embeddings=[[float(x) for x in vector] for vector in stored["embeddings"]])
    return collection


def main():
    parser = argparse.ArgumentParser(description="Compare approximate and exact dense search.")
    parser.add_argument("--file", default=DEFAULT_QUESTIONS, help="questions to ask, one per line")
    parser.add_argument("--k", type=int, default=settings.top_k, help="how many chunks to compare")
    parser.add_argument("--show", type=int, default=3, help="how many disagreements to print in detail")
    parser.add_argument("--ef-search", type=int, default=None,
                        help="compare a tuned throwaway copy of the approximate index (search width N)")
    parser.add_argument("--save", action="store_true", help="append this run to docs/hardening/ann-vs-exact.md")
    args = parser.parse_args()
    make_output_safe()

    if args.k < 1:
        print(f"Error: --k must be 1 or greater, got {args.k}.")
        return 1
    if args.ef_search is not None and args.ef_search < 1:
        print(f"Error: --ef-search must be 1 or greater, got {args.ef_search}.")
        return 1
    if store.count_chunks() == 0:
        print("Error: nothing is indexed yet. Run `python scripts/ingest.py` first.")
        return 1
    questions = load_questions(args.file)
    if not questions:
        print(f"No questions found in {display_path(args.file, BASE_DIR)}.")
        return 1

    vectors = embed_texts(questions)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
        tuned = _tuned_collection(args.ef_search, scratch) if args.ef_search else None
        rows = []
        for question, vector in zip(questions, vectors):
            if tuned is not None:
                approximate = tuned.query(query_embeddings=[[float(x) for x in vector]], n_results=args.k)
            else:
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
    kind = f"tuned approximate (HNSW, ef_search={args.ef_search})" if args.ef_search else "approximate (HNSW, Chroma default)"

    lines = []

    def emit(text=""):
        print(text)
        lines.append(text)

    emit(f"=== {kind} vs exact dense search, k={args.k}, {total} questions ===")
    emit(f"index: {store.count_chunks()} chunks, embeddings: {settings.embed_provider}")
    emit(f"top-1 chunk differs from exact : {len(top1_differs)}/{total}  ({len(top1_differs) / total:.0%})")
    emit(f"top-{args.k} set differs from exact : {len(set_differs)}/{total}  ({len(set_differs) / total:.0%})")
    emit(f"mean overlap@{args.k}                : {overlap:.3f}   (1.000 means identical)")
    for row in top1_differs[:max(args.show, 0)]:
        emit(f"\n  Q: {row['question']}")
        emit(f"     exact search : {row['exact_ids'][:2]}  scores {row['exact_scores'][:2]}")
        emit(f"     approximate  : {row['ann_ids'][:2]}  scores {row['ann_scores'][:2]}")
    emit("\nThis run is one draw: run it again and the counts may move. Exact search never does.")

    if args.save:
        os.makedirs(os.path.dirname(SAVE_PATH), exist_ok=True)
        new_file = not os.path.exists(SAVE_PATH)
        with open(SAVE_PATH, "a", encoding="utf-8") as handle:
            if new_file:
                handle.write("# Approximate vs exact dense search (generated)\n\n"
                             "Each block is one run of `python scripts/compare_ann_exact.py --save` "
                             "(optionally with `--ef-search N`). Blocks are appended, so the spread between runs is visible.\n")
            command = "python scripts/compare_ann_exact.py" + (f" --ef-search {args.ef_search}" if args.ef_search else "") + " --save"
            handle.write(f"\n## {datetime.now().isoformat(timespec='seconds')}  `{command}`\n\n```\n" + "\n".join(lines) + "\n```\n")
        print(f"\nAppended to {display_path(SAVE_PATH, BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
