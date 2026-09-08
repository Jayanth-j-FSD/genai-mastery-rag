"""Week 4, mentor check #1 — label every failure as RETRIEVAL or GENERATION, with evidence.

This runs each labelled question through the real pipeline and prints,
side by side, what was fetched and what was answered — then names which of the two
kinds of failure it is and why. That printout is the evidence to put in front of your
mentor when asked "which kind is this one, and how do you know?".

It defaults to `--mode dense`, the Week 3 search, because the task is to diagnose the
app *as it was* before this week's change. Re-run with `--mode hybrid` afterwards to
see which labels moved.

This one DOES call the answer model (once per question), so it costs a little. Use
`--no-model` for a free retrieval-only pass.

Run:
    python scripts/diagnose_failures.py
    python scripts/diagnose_failures.py --mode hybrid --save
    python scripts/diagnose_failures.py --no-model
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings, BASE_DIR                      # noqa: E402
from app.rag.diagnose import classify, NON_FAILURE_KINDS       # noqa: E402
from tests.eval_set import CASES                                # noqa: E402


def _format_case(result):
    """Render one diagnosis as a readable block: question / fetched / answer / verdict."""
    lines = []
    kind = result["kind"] or "NOT GRADED"
    lines.append(f"[{kind}] {result['question']}")
    expected = result["expected_sources"] or ["(nothing — must refuse)"]
    lines.append(f"    expected : {', '.join(expected)}")

    lines.append(f"    fetched  : {len(result['retrieved'])} chunk(s) at k={result['k']}")
    for row in result["retrieved"]:
        found_by = "+".join(row["retrievers"]) or "?"
        ranks = []
        if row["dense_rank"] is not None:
            ranks.append(f"dense#{row['dense_rank']}")
        if row["keyword_rank"] is not None:
            ranks.append(f"keyword#{row['keyword_rank']}")
        detail = f" ({', '.join(ranks)})" if ranks else ""
        score = row["score"] if row["score"] is not None else 0.0
        marker = "*" if row["source"] in (result["expected_sources"] or []) else " "
        lines.append(f"      {marker} {row['rank']}. {row['source']:<20} "
                     f"score={score:<7} via {found_by}{detail}")
        lines.append(f"          {row['snippet']}")

    if result["answer"] is not None:
        lines.append(f"    answered : {result['answer']}")
        lines.append(f"    grounded : {result['grounded']}")
    lines.append(f"    verdict  : {result['why']}")
    return lines


def main():
    parser = argparse.ArgumentParser(
        description="Label each question's failure as RETRIEVAL or GENERATION.")
    parser.add_argument("--mode", choices=["dense", "hybrid"], default="dense",
                        help="which search to diagnose (default: dense, the Week 3 search)")
    parser.add_argument("--no-model", action="store_true",
                        help="skip the answer model — retrieval-only, free but partial")
    parser.add_argument("--failures-only", action="store_true",
                        help="print only the cases that are not passing")
    parser.add_argument("--save", action="store_true",
                        help="also write the report to docs/week4/failure-labels-<mode>.md")
    args = parser.parse_args()

    lines = []

    def emit(text=""):
        print(text)
        lines.append(text)

    emit(f"=== Failure diagnosis — mode={args.mode}, k={settings.top_k} ===")
    emit("'*' marks a chunk from a document that legitimately answers the question.")
    if args.no_model:
        emit("(--no-model: the answer model was NOT called, so refusal cases are ungraded)")
    emit()

    counts = {}
    try:
        for case in CASES:
            result = classify(case, mode=args.mode, call_model=not args.no_model)
            kind = result["kind"] or "NOT GRADED"
            counts[kind] = counts.get(kind, 0) + 1
            if args.failures_only and kind in NON_FAILURE_KINDS:
                continue
            for line in _format_case(result):
                emit(line)
            emit()
    except RuntimeError as exc:              # missing documents, no API key configured
        print(f"Error: {exc}")
        return 1
    except Exception as exc:                 # e.g. a rejected API key, or no index yet
        print(f"Error ({type(exc).__name__}): {exc}")
        print("Have you run `python scripts/ingest.py` and set OPENAI_API_KEY in .env?")
        return 1

    emit("--- summary ---")
    for kind in sorted(counts):
        emit(f"  {kind:<12} {counts[kind]}")
    emit()
    emit("RETRIEVAL failures need a better search. GENERATION failures need a better "
         "prompt or better chunks. A smarter answer model fixes only the second kind.")

    if args.save:
        out_path = os.path.join(BASE_DIR, "docs", "week4",
                                f"failure-labels-{args.mode}.md")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# Week 4 — failure labels ({args.mode} search)\n\n")
            f.write(f"Generated {datetime.now().isoformat(timespec='seconds')} by "
                    f"`python scripts/diagnose_failures.py --mode {args.mode} --save`.\n\n")
            f.write("```\n" + "\n".join(lines) + "\n```\n")
        print(f"\nSaved: {os.path.relpath(out_path, BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
