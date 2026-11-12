"""Week 10, mentor check #3: did the team race do what was predicted BEFORE it was run?

`docs/week10/prediction.md` states, in a document committed before the first race run, what the team should do
and what would count as the prediction failing. This reads a saved race and checks each sentence against the numbers, so
the answer is arithmetic and not a judgement made after seeing the result. It decides nothing about which design to use.

The thresholds were registered for 9 tasks x 3 repeats = 27 units. A race that stopped early, has a different size, or has no
usable unit gets no verdict: the script says so and exits with 1, the same as for a race it cannot check at all.

Run:
    python scripts/check_team_prediction.py wk10
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.console import make_output_safe                     # noqa: E402
from evals import runner, team_prediction                    # noqa: E402


def current_prediction_state():
    """(git blob of the committed prediction document, hash of evals/team_prediction.py) as they are now; None for what cannot be read."""
    import race_team                                          # here and not at the top: it imports the whole app, and the other modes of this script do not need it
    return race_team.prediction_doc_state()[0], race_team.file_sha("evals/team_prediction.py")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check the pre-registered team prediction against a saved race.")
    parser.add_argument("label", help="the label of the saved race (evals/results/race-<label>.json)")
    args = parser.parse_args(argv)
    make_output_safe()
    try:
        saved = runner.load_results("race-" + args.label)
    except (FileNotFoundError, ValueError) as exc:                   # a missing file, or one cut off by a crash or edited by hand
        print(f"Error: {exc}")
        return 1
    rows, failed, dropped = team_prediction.check_prediction(saved)
    print("\n".join(team_prediction.format_prediction(rows, failed, dropped, args.label)))
    if not rows:
        print(f"Why: {team_prediction.why_not_checkable(saved)}")
    changed, unverified = team_prediction.drift_notes(saved.get("meta"), *current_prediction_state())
    for note in unverified:
        print(f"NOTE: {note}.")
    for note in changed:
        print(f"WARNING: {note}.")
    if changed:
        print("WARNING: the prediction was changed after the race began, so what is printed above is not the pre-registered prediction checked against the race. "
              "No clean verdict.")
    return 0 if rows and failed is not None and not changed else 1      # no verdict (nothing to check, partial, no data, a changed prediction) is not a clean run


if __name__ == "__main__":
    sys.exit(main())
