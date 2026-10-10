"""Command-line tool: build the index from data/corpus/.

Run this once (and again whenever you change the documents or the
chunk size):  python scripts/ingest.py
"""
import os
import sys

# Let this script find the "app" package when run directly from the project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rag.pipeline import ingest  # noqa: E402  (import must follow the path setup above)


if __name__ == "__main__":
    try:
        result = ingest()
    except RuntimeError as exc:            # e.g. no documents / no API key
        print(f"Error: {exc}")
        sys.exit(1)

    print(f"Ingested {result['documents']} document(s) into {result['chunks']} chunk(s).")
    if result.get("chunks_removed_by_cleaning"):
        print(f"  ({result['chunks_removed_by_cleaning']} chunk(s) fewer than a plain ingest, because "
              "DEDUPE_CHUNKS or BOILERPLATE_MIN_REPEATS is on)")
    # Show how each document was split, so the chunking is visible (supports check #4).
    for source, count in sorted(result.get("per_source", {}).items()):
        print(f"  - {source}: {count} chunk(s)")
