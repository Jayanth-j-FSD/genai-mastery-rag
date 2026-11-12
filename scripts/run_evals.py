"""Week 6, mentor check #1: the whole eval set, with ONE command.

This asks the app every question in the eval set, scores each answer with free rule
checks (did it cite the right document? did it refuse when it should have? does it contain the
facts?) and an AI judge, and prints a score for each kind of problem. It saves the run so two
runs can be compared before and after a change.

Run:
    python scripts/run_evals.py                              # everything, saved as evals/results/latest.json
    python scripts/run_evals.py --label baseline             # name the run
    python scripts/run_evals.py --label after --set retrieval_mode=hybrid   # change ONE setting
    python scripts/run_evals.py --no-judge                   # rules only, no judge calls
    python scripts/run_evals.py --only code-err4032 absent-bonus
    python scripts/run_evals.py --clean-indexes              # delete the private eval indexes

Calls to the models are cached by their exact input, so repeating a run, or running a variant that
changes only some questions' context, costs nothing for the unchanged ones. If a daily quota runs
out the run saves what it finished and stops; run it again later to resume.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import BASE_DIR, settings                    # noqa: E402
from app.console import display_path, make_output_safe       # noqa: E402
from evals import judge, report, runner                      # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the eval set and score every answer.")
    parser.add_argument("--label", default="latest", help="name of this run (default: latest)")
    parser.add_argument("--no-judge", action="store_true", help="rule checks only: no judge calls")
    parser.add_argument("--no-cache", action="store_true", help="ask the models again even if the input is unchanged")
    parser.add_argument("--only", nargs="+", metavar="ID", help="run only these case ids")
    parser.add_argument("--types", nargs="+", metavar="TYPE", help="run only these problem types")
    parser.add_argument("--limit", type=int, help="run only the first N cases")
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                        help="override ONE setting for this run, e.g. --set top_k=2 (repeatable)")
    parser.add_argument("--min-score", type=float, metavar="FRACTION",
                        help="exit with status 2 if the overall score is below this (0 to 1), for use as a gate")
    parser.add_argument("--clean-indexes", action="store_true", help="delete the private eval indexes and exit")
    args = parser.parse_args(argv)
    make_output_safe()

    if args.clean_indexes:
        print(f"Removed {runner.clean_indexes()} private eval index(es). The main index was not touched.")
        return 0

    try:
        overrides = runner.parse_overrides(args.set)
        with runner.overridden(overrides):                  # validate now, so a bad value fails before anything runs
            pass
        cases = runner.select_cases(args.only, args.types, args.limit)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    if not cases:
        print("No cases selected.")
        return 1

    try:
        with runner.overridden(overrides):
            # The header is printed INSIDE the override, so it names the models this run really uses.
            judge_note = "no judge" if args.no_judge else f"judge {judge.judge_model()}"
            print(f"Running {len(cases)} case(s): answer model {settings.llm_model}, {judge_note}"
                  + (f", overrides {overrides}" if overrides else ""))
            if args.no_judge is False and judge.judge_model() == settings.llm_model:
                print("Note: JUDGE_MODEL is not set, so the answer model also judges its own answers. "
                      "Set JUDGE_MODEL to a different model for a fairer judge.")
            print()
            results = runner.run_cases(cases, label=args.label, with_judge=not args.no_judge,
                                       use_cache=not args.no_cache, overrides=overrides)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1
    path = runner.save_results(results)
    if path.endswith(".incomplete.json"):
        print("\nNote: this run stopped early, so it was saved beside the earlier complete run with the same label, "
              "which was kept.")

    print()
    for line in report.format_summary(results):
        print(line)
    meta = results["meta"]
    print(f"\nsaved: {display_path(path, BASE_DIR)}   (cache hits: {meta['cache_hits']}, "
          f"calls: {meta['usage']['calls']}, tokens: {meta['usage']['prompt_tokens']} in / {meta['usage']['completion_tokens']} out)")
    if not meta["complete"]:
        return 1
    if args.min_score is not None and report.headline(report.summarize(results)["overall"]) < args.min_score:
        print(f"Overall score is below the required {args.min_score:.0%}.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
