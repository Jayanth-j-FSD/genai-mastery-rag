"""Week 8, mentor check #3: the before-and-after number on the top failure mode.

After you fix one failure mode, run `run_trajectories.py` again under a new label and compare
the two saved runs here. The table shows, for both runs, how many answers were right, how many paths were
clean, how many runs fell in the "right answer, wrong path" gap, how often each failure mode appeared, and
what a run cost. One fix, one measured change.

Run:
    python scripts/compare_trajectories.py before after
    python scripts/compare_trajectories.py before after --save        # also write docs/week8/before-after.md
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import BASE_DIR                              # noqa: E402
from app.console import display_path, make_output_safe       # noqa: E402
from evals import runner, trajectory                         # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare two saved trajectory runs.")
    parser.add_argument("before", help="label of the run before the fix")
    parser.add_argument("after", help="label of the run after the fix")
    parser.add_argument("--save", action="store_true", help="also write docs/week8/before-after.md")
    args = parser.parse_args(argv)
    make_output_safe()

    try:
        before = runner.load_results("trajectories-" + args.before)
        after = runner.load_results("trajectories-" + args.after)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        print("Make a run first:  python scripts/run_trajectories.py --label before")
        return 1
    lines = trajectory.format_compare(before["summary"], after["summary"], args.before, args.after)
    lines.append("")
    lines.append(f"overrides: before {before['meta'].get('overrides') or 'none'}, after {after['meta'].get('overrides') or 'none'}; "
                 f"defences: before {'on' if before['meta'].get('defense') else 'off'}, after {'on' if after['meta'].get('defense') else 'off'}")
    lines.append(f"With {before['summary']['runs']} and {after['summary']['runs']} runs, a difference of one or two runs is within what "
                 "a second identical run could change. Read the modes, not only the totals.")
    print("\n".join(lines))
    if args.save:
        path = os.path.join(BASE_DIR, "docs", "week8", "before-after.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("# Week 8: the before-and-after on the top failure mode (generated)\n\n")
            handle.write(f"Generated {datetime.now().isoformat(timespec='seconds')} by "
                         f"`python scripts/compare_trajectories.py {args.before} {args.after} --save`. Numbers only.\n\n")
            handle.write("```\n" + "\n".join(lines) + "\n```\n")
        print(f"\nsaved: {display_path(path, BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
