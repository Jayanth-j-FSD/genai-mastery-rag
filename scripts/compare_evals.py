"""Week 6, mentor check #4: the before-and-after score, per problem type.

After you change one thing, run the eval set again under a new label and compare the
two runs. The table shows each kind of problem before and after, and names the individual cases the
change fixed, broke, or left failing, so a gain can be traced to specific questions.

Run:
    python scripts/compare_evals.py baseline after
    python scripts/compare_evals.py baseline after --save     # also write docs/week6/before-after.md
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import BASE_DIR                              # noqa: E402
from app.console import display_path, make_output_safe       # noqa: E402
from evals import report, runner                             # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare two saved eval runs.")
    parser.add_argument("before", help="label or path of the run before the change")
    parser.add_argument("after", help="label or path of the run after the change")
    parser.add_argument("--save", action="store_true", help="also write docs/week6/before-after.md")
    args = parser.parse_args(argv)
    make_output_safe()

    try:
        before, after = runner.load_results(args.before), runner.load_results(args.after)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        print("Make a run first:  python scripts/run_evals.py --label baseline")
        return 1
    for name, run in (("before", before), ("after", after)):
        if not run["meta"].get("complete", True):
            print(f"Warning: the {name} run is incomplete ({run['meta'].get('stopped_because')}). "
                  "Finish it before trusting a comparison.")

    lines = report.format_compare(before, after)
    for line in lines:
        print(line)

    if args.save:
        out_path = os.path.join(BASE_DIR, "docs", "week6", "before-after.md")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write("# Week 6: before and after (generated)\n\n")
            handle.write(f"Generated {datetime.now().isoformat(timespec='seconds')} by "
                         f"`python scripts/compare_evals.py {args.before} {args.after} --save`. "
                         "Numbers only: what they mean is yours to write in `findings.md`.\n\n")
            handle.write("```\n" + "\n".join(lines) + "\n```\n")
        print(f"\nsaved: {display_path(out_path, BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
