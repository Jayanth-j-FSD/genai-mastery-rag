"""Week 10, mentor check #3: did the team race do what was predicted BEFORE it was run?

`docs/week10/CHANGES.md` states, in a section committed before the first race run, what the team should do
and what would count as the prediction failing. This reads a saved race and checks each sentence against the numbers, so
the answer is arithmetic and not a judgement made after seeing the result. It decides nothing about which design to use.

Run:
    python scripts/check_team_prediction.py wk10
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.console import make_output_safe                     # noqa: E402
from evals import runner, team_prediction                    # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check the pre-registered team prediction against a saved race.")
    parser.add_argument("label", help="the label of the saved race (evals/results/race-<label>.json)")
    args = parser.parse_args(argv)
    make_output_safe()
    try:
        saved = runner.load_results("race-" + args.label)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return 1
    rows, failed, dropped = team_prediction.check_prediction(saved)
    print("\n".join(team_prediction.format_prediction(rows, failed, dropped, args.label)))
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
