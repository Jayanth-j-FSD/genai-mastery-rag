"""Week 11, mentor check #3: measure what a request costs, with and without an idea, and see whether the answers stayed right.

This asks the same questions under two or more ARMS (an arm is a name plus the settings it changes) through the
real answer path, interleaved so the provider's mood hits every arm equally, with `before` asked twice as a noise floor. Every
request is logged like a user's would be, so what it spent is read from the log: tokens, time, and the time spent waiting for
the rate limit apart from the time at the provider. Eval questions are also scored by the free Week 6 rules.

Run (the model is always named, never an alias):
    python scripts/measure_cost.py --label w11 --model gemini-3.1-flash-lite-preview --dry-run          # no quota: a scripted provider
    python scripts/measure_cost.py --label w11 --model gemini-3.1-flash-lite-preview --only absent-bonus code-err4032 --limit 2
    python scripts/measure_cost.py --label w11 --model gemini-3.1-flash-lite-preview --bank 30 --seed 42
    python scripts/measure_cost.py --label x --model M --arm before --arm "after:context_strip_min_repeats=10" --arm before-2

The default arms are `before`, `after:context_strip_min_repeats=10` and `before-2`. Each arm's raw log goes to
data/measure/<label>/<arm>/ (untracked); the result kept for the repository is evals/results/cost-<label>.json, one row per request
and no text. Read it with scripts/cost_report.py. A run that stops (daily quota, the provider failing three times in a row, the
--max-calls budget) saves what it finished and says why. It refuses to overwrite an earlier label unless you pass --force.
"""
import argparse
import contextlib
import os
import shutil
import sys

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import BASE_DIR, settings                  # noqa: E402
from app.console import display_path, make_output_safe     # noqa: E402
from evals import bank, cost_run, runner                    # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Measure what a request costs under two or more arms, interleaved.")
    parser.add_argument("--label", required=True, help="name of this measurement; the result is evals/results/cost-<label>.json")
    parser.add_argument("--model", help="the answer model, always named (required unless --dry-run)")
    parser.add_argument("--arm", action="append", default=[], metavar="NAME[:setting=value,...]",
                        help="an arm (repeatable); default: before, after:context_strip_min_repeats=10, before-2")
    parser.add_argument("--only", nargs="+", metavar="ID", help="ask only these eval case ids")
    parser.add_argument("--bank", type=int, default=0, metavar="N", help="also ask N questions drawn from the Week 5 bank (not scored)")
    parser.add_argument("--seed", type=int, default=42, help="seed for the bank draw (default 42)")
    parser.add_argument("--limit", type=int, metavar="N", help="ask only the first N questions after the list is built")
    parser.add_argument("--max-calls", type=int, default=400, help="stop before spending more model calls than this (default 400)")
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="change ONE setting for every arm (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="answer from a scripted stand-in for the provider: no quota, numbers are not measurements")
    parser.add_argument("--force", action="store_true", help="replace an earlier measurement with the same label")
    args = parser.parse_args(argv)
    make_output_safe()

    if not args.dry_run and not args.model:
        print("Error: --model is required: name the model (not an alias like gemini-flash-lite-latest) so the result says what it measured.")
        return 1
    if args.max_calls < 1:
        print("Error: --max-calls must be 1 or more.")
        return 1
    try:
        arms = cost_run.parse_arms(args.arm or cost_run.DEFAULT_ARMS)
        shared = runner.parse_overrides(args.set)
        cases = runner.select_cases(args.only)
        with runner.overridden(shared):
            pass
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    label = f"dry-{args.label}" if args.dry_run else args.label
    out_dir = os.path.join(cost_run.MEASURE_DIR, runner.safe_label(label))
    saved_path = os.path.join(out_dir, "cost-dry.json") if args.dry_run else cost_run.results_path(label)
    if (os.path.exists(out_dir) or (not args.dry_run and cost_run.aggregate_exists(label))) and not args.force:
        print(f"Error: a measurement called {label!r} already exists. Use another --label, or --force to replace it.")
        return 1

    questions = bank.sample(bank.load_questions(), args.bank, args.seed, exclude=[case["question"] for case in cases]) if args.bank else []
    items = cost_run.make_items(cases, questions)
    if args.limit:
        items = items[:args.limit]
    if not items:
        print("No questions selected.")
        return 1
    planned = len(items) * len(arms)
    if planned > args.max_calls:
        print(f"Error: {len(items)} questions x {len(arms)} arms is {planned} model calls, over --max-calls {args.max_calls}. "
              f"Raise it, or narrow the questions with --only / --limit.")
        return 1

    model = args.model or "scripted-model"
    with runner.overridden({**shared, **({"llm_rpm": 0} if args.dry_run else {})}):
        minutes = f", about {planned / settings.llm_rpm:.0f} minutes at {settings.llm_rpm} calls a minute" if settings.llm_rpm and not args.dry_run else ""
        print(("DRY RUN (scripted provider, no quota). " if args.dry_run else "") + f"{len(items)} questions x {len(arms)} arms "
              f"({', '.join(name for name, _ in arms)}) = {planned} requests{minutes}; model {model}; logs in {display_path(out_dir, BASE_DIR)}\n")
        if args.force and os.path.isdir(out_dir) and os.path.commonpath([out_dir, cost_run.MEASURE_DIR]) == cost_run.MEASURE_DIR:
            shutil.rmtree(out_dir)                       # the raw logs of the measurement being replaced, nothing else
        try:
            with (cost_run.scripted_provider() if args.dry_run else contextlib.nullcontext()):
                results = cost_run.run(items, arms, label, model, out_dir, max_calls=args.max_calls, dry_run=args.dry_run,
                                       save=lambda r: cost_run.save_aggregate(r, saved_path))
        except (RuntimeError, ValueError) as exc:
            print(f"Error: {exc}")
            return 1

    print()
    print("\n".join(cost_run.format_summary(results)))
    print(f"\nsaved: {display_path(saved_path, BASE_DIR)}")
    return 0 if results["meta"]["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
