"""Week 11: check the pre-registered prediction for the cost measurement against a saved measurement.

Docs/week11/prediction.md says, in numbers, how much cheaper the one improvement should make a request and what
would count as the prediction failing. It was written before the first request went to the model. This script turns those sentences
into arithmetic over the saved measurement (evals/results/cost-<label>.json) so nobody has to decide afterwards whether it held.
A dry run, a measurement that stopped early, one made under other settings and one that did not ask the registered questions are given no verdict.

Run:
    python scripts/check_cost_prediction.py LABEL
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.console import make_output_safe        # noqa: E402
from evals import cost_prediction, cost_run     # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check the cost prediction against a saved measurement.")
    parser.add_argument("label", help="the label of the measurement (or the path of its cost-<label>.json)")
    args = parser.parse_args(argv)
    make_output_safe()
    try:
        results = cost_run.load_aggregate(args.label)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1
    check = cost_prediction.check_prediction(results)
    print("\n".join(cost_prediction.format_prediction(check)))
    return 0 if check["verdict"] else 1


if __name__ == "__main__":
    sys.exit(main())
