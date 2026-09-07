"""Command-line tool: ask one question.

Run:  python scripts/ask.py "how many leave days carry over?"
"""
import os
import sys

# Let this script find the "app" package when run directly from the project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rag.pipeline import answer  # noqa: E402


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python scripts/ask.py "your question"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])   # join the words so surrounding quotes are optional
    try:
        result = answer(question)
    except RuntimeError as exc:          # e.g. no API key configured
        print(f"Error: {exc}")
        sys.exit(1)

    print("\nANSWER:")
    print(result["answer"])
    if result["sources"]:
        print("\nSOURCES:")                       # mentor check #2 — visible in the terminal
        for s in result["sources"]:
            print(f"  - {s['document']}  (score {s['score']})")
    else:
        print("\n(No sources — the answer was not found in the documents.)")
