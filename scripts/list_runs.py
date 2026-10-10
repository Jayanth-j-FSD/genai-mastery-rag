"""Week 6: list every saved eval run with its scores, as one table.

After a few experiments you have several result files. This puts them side by side so the
whole story (the baseline, each change, what each did to the score) reads in one place. The numbers are
case counts, not percentages: with 41 cases a single case is 2.4 points.

Run:
    python scripts/list_runs.py
    python scripts/list_runs.py --markdown        # a table you can paste into a document
    python scripts/list_runs.py baseline wide     # only these labels, in this order
"""
import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.console import make_output_safe        # noqa: E402
from evals import report, runner                # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="List saved eval runs and their scores.")
    parser.add_argument("labels", nargs="*", help="labels to show, in order (default: every saved run, alphabetical)")
    parser.add_argument("--markdown", action="store_true", help="print a markdown table")
    args = parser.parse_args(argv)
    make_output_safe()

    try:
        if args.labels:
            runs = [runner.load_results(label) for label in args.labels]
            for label, run in zip(args.labels, runs):
                if "cases" not in run:
                    raise FileNotFoundError(f"'{label}' is not an eval run (it has no cases); the other kinds of saved run have their own scripts")
        else:
            paths = sorted(glob.glob(os.path.join(runner.RESULTS_DIR, "*.json")))       # by name: file times mean nothing after a clone
            loaded = [runner.load_results(path) for path in paths]
            runs = [run for run in loaded if "cases" in run]       # races, trajectory runs and injection runs live here too
            if len(runs) < len(loaded):
                print(f"({len(loaded) - len(runs)} saved file(s) are not eval runs, such as races, and are skipped.)\n")
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return 1
    if not runs:
        print("No saved runs yet. Make one first:  python scripts/run_evals.py --label baseline")
        return 1
    print("\n".join(report.format_runs(runs, markdown=args.markdown)))
    incomplete = [r["meta"]["label"] for r in runs if not r["meta"].get("complete", True)]
    if incomplete:
        print(f"\nIncomplete runs (a quota ran out): {incomplete}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
