"""Week 6, mentor check #2: turn last week's real failures into permanent tests.

Week 5 found real bad answers and you wrote an honest note and a group name for each
(`docs/week5/coded-notes.md`). Those are the most valuable test cases you will ever have, because the
app really did get them wrong. This turns every one into an eval case, so a fix that quietly breaks
it again is caught. The group name you chose becomes the case's problem type, so the scores are
reported per YOUR named problem.

What it cannot do is decide what the RIGHT answer was: your notes say what went wrong, not what a
correct answer says. So each case is written out with empty expectations, and you fill in the ones
that apply (see the instructions inside the file). Until you do, the case is still run and judged, but
only the rule that checks refusal and the AI judge apply, and the run says so.

Run:
    python scripts/make_regressions.py            # reads docs/week5/coded-notes.md
    python scripts/make_regressions.py --force    # regenerate (DELETES expectations you filled in)
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import worksheet                                    # noqa: E402
from app.config import BASE_DIR                              # noqa: E402
from app.console import display_path, make_output_safe       # noqa: E402
from evals.cases import REGRESSIONS_PATH                     # noqa: E402

DEFAULT_IN = os.path.join(BASE_DIR, "docs", "week5", "coded-notes.md")

INSTRUCTIONS = [
    "Each case below is one of your Week 5 failures. Fill in what a CORRECT answer looks like:",
    "  expected_sources  documents that legitimately answer it, e.g. [\"Acme-Leave-Policy-2026.md\"]",
    "  expect_contains   phrases of which a correct answer contains at least one, e.g. [\"16 weeks\"]",
    "  expect_all        phrases that must ALL appear (for list answers)",
    "  should_refuse     true if the documents cannot answer it and the right reply is \"I don't know\"",
    "  reference         one human-written sentence saying what the correct answer is (helps the judge)",
    "Leave a case with expected_sources empty and should_refuse false and it is still run and judged,",
    "but only the refusal rule and the judge apply. Every phrase must be in the documents: check it.",
]


def build_cases(blocks):
    """One case per failure. problem_type is your own group name."""
    cases = []
    for block in worksheet.failures(blocks):
        cases.append({
            "id": f"w5-{block['trace_id']}",
            "question": block["question"],
            "problem_type": worksheet.normalize_code(block["code"]),
            "origin": f"week5:{block['trace_id']}",
            "failing_answer": block["answer"],
            "your_note": block["note"],
            "severity": block["severity"],
            "expected_sources": [],
            "expect_contains": [],
            "expect_all": [],
            "should_refuse": False,
            "reference": "",
        })
    return cases


def main(argv=None):
    parser = argparse.ArgumentParser(description="Turn Week 5 failures into eval cases.")
    parser.add_argument("--in", dest="source", default=DEFAULT_IN, help="the coded notes (default docs/week5/coded-notes.md)")
    parser.add_argument("--out", default=REGRESSIONS_PATH, help="where to write the cases (default evals/regressions.json)")
    parser.add_argument("--force", action="store_true", help="overwrite existing cases (DELETES expectations you filled in)")
    args = parser.parse_args(argv)
    make_output_safe()

    try:
        blocks, _ = worksheet.parse(args.source)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        print("These come from your Week 5 reading. Do that first:  see docs/week5/README.md")
        return 1
    failures = worksheet.failures(blocks)
    if not failures:
        print("There are no failures in the coded notes, so there is nothing to turn into a test.")
        return 1
    uncoded = [block["trace_id"] for block in failures if not worksheet.normalize_code(block["code"])]
    if uncoded:
        print(f"{len(uncoded)} failure(s) have no group name yet ({', '.join(uncoded)}).")
        print("Name every group in coded-notes.md first: the group becomes the problem type.")
        return 1
    if os.path.exists(args.out) and not args.force:
        print(f"Error: {display_path(args.out, BASE_DIR)} already exists and may hold expectations you wrote.")
        print("Pass --force only if you really want to regenerate it.")
        return 1

    cases = build_cases(blocks)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump({"generated": datetime.now().isoformat(timespec="seconds"),
                   "source": os.path.basename(args.source), "instructions": INSTRUCTIONS, "cases": cases},
                  handle, ensure_ascii=False, indent=1)
    print(f"Wrote {len(cases)} regression case(s) to {display_path(args.out, BASE_DIR)}")
    print("Next: fill in expected_sources / expect_contains / should_refuse for each, then")
    print("      python scripts/run_evals.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
