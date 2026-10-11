"""Week 8: do the defences block legitimate work? Replay saved runs through them (free: no model calls).

`run_trajectories.py --defense` answers this with live model calls. This answers it from runs you
already saved, in seconds, on whatever the defence code is today. Use it after changing a defence.

Run:
    python scripts/replay_defense.py before before-p control        # saved trajectory runs, by label
    python scripts/replay_defense.py race-race                      # a saved Week 7 race (its agent runs)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.console import make_output_safe                     # noqa: E402
from evals import injection, replay, runner                  # noqa: E402
from evals.agent_tasks import get_tasks                      # noqa: E402


def load(label):
    """A saved trajectory run by its label, or any saved results file by its name."""
    for candidate in ("trajectories-" + label, label):
        try:
            return runner.load_results(candidate)
        except FileNotFoundError:
            continue
    raise FileNotFoundError(f"No saved run called '{label}' (looked for trajectories-{label} and {label})")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Replay saved runs through the defences and report what they would have blocked.")
    parser.add_argument("labels", nargs="+", metavar="LABEL", help="saved runs made with the defences off")
    args = parser.parse_args(argv)
    make_output_safe()
    tasks, trusted = get_tasks(None, include_probes=True), injection.trusted_contacts()
    code = 0
    for label in args.labels:
        try:
            saved = load(label)
        except FileNotFoundError as exc:
            print(f"Error: {exc}")
            code = 1
            continue
        if saved.get("meta", {}).get("defense"):
            print(f"'{label}' was made WITH the defences on, so its observations are already screened: nothing to replay.")
            code = 1
            continue
        print("\n".join(replay.format_replay(label, replay.replay_runs(saved["runs"], tasks, trusted))) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
