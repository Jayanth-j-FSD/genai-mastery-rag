"""Week 5 step 1 — run a batch of questions through the app so traces accumulate.

Week 5's task is to read about 20 *real* answers your app gave. To
have 20 real answers you first have to ask 20 real questions. This runs a whole
question bank through the normal answer path, which means every one is logged to
`data/traces/traces.jsonl` exactly like a user request.

It deliberately goes through `pipeline.answer()` rather than calling the retriever
and generator directly — that is the only path that writes a trace.

Cost: one embedding call and one small answer call per question. With gpt-4o-mini and
this short corpus that is fractions of a cent per question, but it is not free, so the
question count is printed and confirmed before anything runs.

Run:
    python scripts/ask_batch.py                          # uses tests/trace_questions.txt
    python scripts/ask_batch.py --file my_questions.txt
    python scripts/ask_batch.py --yes                     # skip the confirmation
    python scripts/ask_batch.py --mode dense              # force a retrieval strategy
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings, BASE_DIR        # noqa: E402
from app.console import display_path               # noqa: E402
from app.rag.pipeline import answer              # noqa: E402

DEFAULT_QUESTIONS = os.path.join(BASE_DIR, "tests", "trace_questions.txt")


def load_questions(path):
    """Read one question per line, ignoring blank lines and # comments."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"No question file at {path}")
    questions = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            questions.append(line)
    return questions


def main():
    parser = argparse.ArgumentParser(
        description="Ask a batch of questions so their traces are logged.")
    parser.add_argument("--file", default=DEFAULT_QUESTIONS,
                        help="question file, one per line (default tests/trace_questions.txt)")
    parser.add_argument("--mode", choices=["dense", "hybrid"], default=None,
                        help="force a retrieval strategy (default: whatever .env says)")
    parser.add_argument("--yes", action="store_true",
                        help="do not ask for confirmation before spending on API calls")
    args = parser.parse_args()

    try:
        questions = load_questions(args.file)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return 1

    if not questions:
        print(f"No questions found in {args.file}.")
        return 1

    mode = args.mode or settings.retrieval_mode
    print(f"About to ask {len(questions)} question(s) using mode={mode}.")
    print(f"That is {len(questions)} embedding call(s) + {len(questions)} answer call(s), "
          f"logged to {display_path(settings.traces_path, BASE_DIR)}.")
    if not args.yes:
        # Cheap, but it is real money and real API calls — make it a deliberate act.
        try:
            reply = input("Continue? [y/N] ").strip().lower()
        except EOFError:
            # No interactive terminal (piped or redirected input): do not guess a yes.
            print("No terminal to confirm on. Re-run with --yes to proceed.")
            return 1
        if reply not in ("y", "yes"):
            print("Cancelled. Nothing was asked.")
            return 0

    answered = refused = failed = 0
    for number, question in enumerate(questions, start=1):
        try:
            result = answer(question, mode)
        except Exception as exc:
            # One bad question must not abandon the rest of the batch.
            failed += 1
            print(f"{number:>3}. FAILED  {question}")
            print(f"     ({type(exc).__name__}) {exc}")
            continue
        if result["grounded"]:
            answered += 1
            label = "answered"
        else:
            refused += 1
            label = "refused "
        sources = ", ".join(s["document"] for s in result["sources"]) or "-"
        print(f"{number:>3}. {label} {question}")
        print(f"     sources: {sources}")

    print(f"\nDone. answered={answered}  refused={refused}  failed={failed}")
    print("Next:  python scripts/sample_traces.py --n 20")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
