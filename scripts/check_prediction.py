"""Week 8, mentor check #3: did the fix do what was predicted BEFORE it was measured?

`docs/week8/CHANGES.md` states, in a section committed before any "after" run, what the per-tool
call budget should do and what would count as it failing. This reads two saved runs and checks each sentence
against the numbers, so the answer is arithmetic and not a judgement made after seeing the result.

Run:
    python scripts/check_prediction.py before-final after-final
    python scripts/check_prediction.py before-final after-final --noise before-final-2   # with the A/A noise floor
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.console import make_output_safe                     # noqa: E402
from evals import prediction, runner                         # noqa: E402
from evals.agent_tasks import get_tasks                      # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check the pre-registered budget prediction against two saved runs.")
    parser.add_argument("before", help="label of the run without the budget")
    parser.add_argument("after", help="label of the run with the budget")
    parser.add_argument("--noise", metavar="LABEL", help="a second run of the same configuration as 'before' (the A/A run), "
                                                         "so token and call changes can be read against run-to-run noise")
    args = parser.parse_args(argv)
    make_output_safe()
    try:
        before = runner.load_results("trajectories-" + args.before)
        after = runner.load_results("trajectories-" + args.after)
        noise = runner.load_results("trajectories-" + args.noise) if args.noise else None
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return 1
    rows, failed, pairs = prediction.check_budget_prediction(before["runs"], after["runs"], get_tasks(None, include_probes=True),
                                                             None if noise is None else noise["runs"])
    warnings = prediction.check_setup(before["meta"], after["meta"], None if noise is None else noise["meta"])
    print("\n".join(prediction.format_prediction(rows, failed, pairs, args.before, args.after, warnings)))
    return 1 if not rows else 0


if __name__ == "__main__":
    sys.exit(main())
