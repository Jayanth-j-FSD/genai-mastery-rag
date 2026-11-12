"""Week 6, mentor check #3, step 1: build the blind sheet you grade by hand.

The AI judge is only worth trusting if it agrees with you. This picks a sample of
answers from your saved runs and writes them into a sheet WITHOUT the judge's verdicts. You grade
them, then `scripts/validate_judge.py` compares your verdicts with the judge's.

Run (after at least one run with the judge):
    python scripts/make_judge_sheet.py --runs baseline --n 20
    python scripts/make_judge_sheet.py --runs baseline degraded --n 24     # more bad answers to grade

A run with a deliberately weakened setting (for example `--set top_k=1`) is a cheap way to get
real bad answers for the judge to be tested on; see docs/week6/README.md.

It never overwrites a sheet you may have started grading, unless you pass --force.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import BASE_DIR                              # noqa: E402
from app.console import display_path, make_output_safe       # noqa: E402
from evals import runner, validation                         # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write the blind judge-validation sheet.")
    parser.add_argument("--runs", nargs="+", required=True, help="labels of saved runs to draw answers from")
    parser.add_argument("--n", type=int, default=20, help="how many answers to grade (default 20)")
    parser.add_argument("--seed", type=int, default=42, help="random seed, so the draw can be reproduced")
    parser.add_argument("--out", default=validation.SHEET_PATH, help="where to write the sheet")
    parser.add_argument("--force", action="store_true", help="overwrite an existing sheet (DELETES your grading)")
    args = parser.parse_args(argv)
    make_output_safe()

    if args.n < 1:
        print(f"Error: --n must be 1 or greater, got {args.n}.")
        return 1
    items_path = os.path.join(os.path.dirname(args.out), "items.json")
    if (os.path.exists(args.out) or os.path.exists(items_path)) and not args.force:
        print(f"Error: {display_path(args.out, BASE_DIR)} already exists and may hold your grading.")
        print("Pass --force only if you really want a fresh sheet.")
        return 1
    try:
        runs = [runner.load_results(label) for label in args.runs]
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        print("Make a run first:  python scripts/run_evals.py --label baseline")
        return 1

    items = validation.collect_items(runs)
    if not items:
        print("Those runs contain no judged answers. Run without --no-judge first.")
        return 1
    sample = validation.pick_sample(items, args.n, args.seed)
    if len(sample) < args.n:
        print(f"Note: only {len(sample)} judged answers exist, so the sheet has {len(sample)}, not {args.n}.")
    validation.write_sheet(sample, args.seed, args.out, items_path)

    flagged = sum(1 for i in sample if not i["entry"]["passed"] or i["entry"]["judge"]["verdict"] == "fail")
    print(f"Wrote {display_path(args.out, BASE_DIR)}  ({len(sample)} answers, seed {args.seed}).")
    print(f"The judge's verdicts are in {display_path(items_path, BASE_DIR)}: do not open it until you have graded.")
    print(f"Of the sample, {flagged} were flagged by the rules or the judge, so there are bad answers to find.")
    print("\nNext: open the sheet and put ok or bad on every verdict line. Then:  python scripts/validate_judge.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
