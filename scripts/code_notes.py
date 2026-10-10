"""Week 5 step 3 — turn the honest notes into named problem groups ("open coding").

"open coding" means you read what you wrote about each failure and only
THEN invent the names of the problem types, from the notes themselves, rather than
sorting into categories you picked in advance. This script enforces that order: it
refuses to run until every trace in the worksheet has a verdict, and every failure has
a note and a severity. Then it carries those failures into a second file where you add
one group name per failure.

Run:
    python scripts/code_notes.py
    python scripts/code_notes.py --force        # overwrite coded-notes.md
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import BASE_DIR                              # noqa: E402
from app.console import display_path               # noqa: E402
from app.worksheet import parse, validate_notes, failures     # noqa: E402

DEFAULT_IN = os.path.join(BASE_DIR, "docs", "week5", "worksheet.md")
DEFAULT_OUT = os.path.join(BASE_DIR, "docs", "week5", "coded-notes.md")

NAMING_RULES = [
    "Name what you OBSERVED, not what you think caused it. "
    "\"cited-the-wrong-document\" is a name; \"embedding-problem\" is a guess.",
    "A stranger who has never seen your documents should understand the name.",
    "Aim for three to six groups across the whole sample. One group per failure means "
    "you have not grouped anything; two groups for twenty failures is probably too coarse.",
    "Reuse a name you already used rather than inventing a near-duplicate. "
    "\"wrong-doc\" and \"wrong-document\" would split one real problem into two.",
    "If a failure genuinely does not fit any group, give it its own name and let the "
    "ranking show it as rare. Do not force it into a group to keep the list tidy.",
]

GOOD_EXAMPLES = [
    "answered-a-different-question",
    "refused-though-the-answer-was-present",
    "cited-the-wrong-document",
    "answer-missing-the-specific-limit",
    "merged-two-policies-into-one-answer",
    "answered-confidently-about-something-absent",
]

BAD_EXAMPLES = [
    "bad-answer  (says nothing a stranger can act on)",
    "model-issue  (a guess at the cause, not an observation)",
    "retrieval  (too broad — every retrieval failure lands here)",
    "trace-7  (not a group at all)",
]


def _coded_file(failure_blocks, sample_size, source_path):
    out = []
    out.append("# Week 5 — coded notes")
    out.append("")
    out.append(f"<!-- sample_size: {sample_size} -->")
    out.append(f"<!-- generated: {datetime.now().isoformat(timespec='seconds')} -->")
    out.append("")
    out.append(f"Carried over from `{os.path.basename(source_path)}`: "
               f"**{len(failure_blocks)} failures** out of **{sample_size} traces read**.")
    out.append("")
    out.append("The notes below are yours, copied unchanged. Add one `code:` per failure — "
               "the name of the problem group it belongs to.")
    out.append("")
    out.append("## How to name a group")
    out.append("")
    for rule in NAMING_RULES:
        out.append(f"- {rule}")
    out.append("")
    out.append("Names that work:")
    out.append("")
    for example in GOOD_EXAMPLES:
        out.append(f"- `{example}`")
    out.append("")
    out.append("Names that do not:")
    out.append("")
    for example in BAD_EXAMPLES:
        out.append(f"- `{example}`")
    out.append("")
    out.append("These are examples of the *shape* of a good name, not a menu. Use the words "
               "from your own notes.")
    out.append("")
    out.append("When every failure has a code, run `python scripts/rank_problems.py`.")
    out.append("")
    out.append("---")
    out.append("")

    for number, block in enumerate(failure_blocks, start=1):
        out.append(f"## trace {block['trace_id']}")
        out.append("")
        out.append(f"*failure {number} of {len(failure_blocks)}*")
        out.append("")
        out.append(f"**Question:** {block['question']}")
        out.append("")
        out.append(f"**Answer:** {block['answer']}")
        out.append("")
        out.append("- verdict: bad")
        out.append(f"- note: {block['note']}")
        out.append(f"- severity: {block['severity']}")
        out.append("- code: ")
        out.append("")
        out.append("---")
        out.append("")

    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="Carry the worksheet's failures into a file where you name the groups.")
    parser.add_argument("--in", dest="source", default=DEFAULT_IN,
                        help="the filled-in worksheet (default docs/week5/worksheet.md)")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help="where to write the coded notes")
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing coded notes (this DELETES codes you wrote)")
    args = parser.parse_args()

    try:
        blocks, _metadata = parse(args.source)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        print("Draw a sample first:  python scripts/sample_traces.py --n 20")
        return 1

    problems = validate_notes(blocks)
    if problems:
        print(f"The notes pass is not finished — {len(problems)} thing(s) to fix in "
              f"{display_path(args.source, BASE_DIR)}:\n")
        for problem in problems:
            print(f"  - {problem}")
        print("\nThis is deliberate. Grouping before every failure has an honest note is "
              "how you end up describing the categories you expected instead of the ones "
              "that are really there.")
        return 1

    failure_blocks = failures(blocks)
    print(f"Read {len(blocks)} trace(s): {len(failure_blocks)} marked bad, "
          f"{len(blocks) - len(failure_blocks)} marked ok.")

    if not failure_blocks:
        print("\nNo failures were marked, so there is nothing to group and no taxonomy to "
              "rank. Either the sample genuinely contains no bad answers — in which case "
              "draw a bigger one with scripts/ask_batch.py and a new seed — or the reading "
              "was too generous. A refusal on an answerable question counts as bad, and so "
              "does a technically-true answer that misses the specific number asked for.")
        return 1

    if os.path.exists(args.out) and not args.force:
        print(f"\nError: {display_path(args.out, BASE_DIR)} already exists and may "
              f"contain codes you wrote. Pass --force to overwrite it.")
        return 1

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(_coded_file(failure_blocks, len(blocks), args.source))

    severities = [b["severity"] for b in failure_blocks if b["severity"]]
    if severities:
        print(f"  severity spread: "
              f"{severities.count(3)} at 3, {severities.count(2)} at 2, "
              f"{severities.count(1)} at 1")
    print(f"\nWrote {display_path(args.out, BASE_DIR)}")
    print("Next: add one `code:` per failure, then  python scripts/rank_problems.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
