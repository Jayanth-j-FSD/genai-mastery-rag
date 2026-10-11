"""Command-line tool: ask one question.

Run:  python scripts/ask.py "how many leave days carry over?"
"""
import os
import sys

# Let this script find the "app" package when run directly from the project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openai                              # noqa: E402
from app import observability              # noqa: E402
from app.console import make_output_safe   # noqa: E402
from app.rag.pipeline import answer        # noqa: E402


def show_request_id():
    """Say which logged request this was (it is on the line in data/traces/traces.jsonl, or in errors.jsonl when it failed)."""
    request_id = observability.last_request_id()
    if request_id:
        print(f"\nrequest id: {request_id}")


if __name__ == "__main__":
    make_output_safe()                      # an odd character in the answer must not crash the script
    if len(sys.argv) < 2:
        print('Usage: python scripts/ask.py "your question"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])   # join the words so surrounding quotes are optional
    try:
        with observability.channel("cli"):
            result = answer(question)
    except RuntimeError as exc:          # e.g. no API key, nothing indexed yet, daily quota used up
        print(f"Error: {exc}")
        show_request_id()
        sys.exit(1)
    except openai.APIError as exc:       # the AI provider refused or failed: rate limit, bad key, network
        print(f"Error: the AI provider call failed ({type(exc).__name__}): {exc}")
        show_request_id()
        sys.exit(1)

    print("\nANSWER:")
    print(result["answer"])
    if result["sources"]:
        print("\nSOURCES:")                       # mentor check #2 — visible in the terminal
        for s in result["sources"]:
            print(f"  - {s['document']}  (score {s['score']})")
    else:
        print("\n(No sources — the answer was not found in the documents.)")
    show_request_id()
