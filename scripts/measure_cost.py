"""Week 11, mentor check #3: measure what a request costs, with and without an idea, and see whether the answers stayed right.

This asks the same questions under two or more ARMS (an arm is a name plus the settings it changes) through the
real answer path, interleaved so the provider's mood hits every arm equally, with `before` asked twice as a noise floor. Every
request is logged like a user's would be, so what it spent is read from the log: tokens, time, and the time spent waiting for
the rate limit apart from the time at the provider. Eval questions are also scored by the free Week 6 rules.

Run (the model is always named, never an alias):
    python scripts/measure_cost.py --label w11 --model gemini-3.1-flash-lite-preview --dry-run          # no quota: a scripted provider
    python scripts/measure_cost.py --label w11 --model gemini-3.1-flash-lite-preview --only absent-bonus code-err4032 --limit 2
    python scripts/measure_cost.py --label w11 --model gemini-3.1-flash-lite-preview --bank 30 --seed 42
    python scripts/measure_cost.py --label w11 --model gemini-3.1-flash-lite-preview --bank 30 --seed 42 --resume     # carry on
    python scripts/measure_cost.py --label x --model M --arm before --arm "after:context_strip_min_repeats=10" --arm before-2

The questions are the 41 base eval cases, whatever failures you have converted into tests since (those are never part of this measurement),
plus a seeded sample of the Week 5 bank if you ask for one. The default arms are `before`, `after:context_strip_min_repeats=10` and `before-2`.
Each arm's raw log goes to data/measure/<label>/<arm>/ (untracked); the result kept for the repository is evals/results/cost-<label>.json, one
row per request and no text. A run that stops (daily quota, the provider failing three times in a row, the --max-calls budget, Ctrl-C) saves what
it finished and says why; so does a run that finished with some failed requests. --resume carries it on: answered requests are kept, failed ones are
asked again, nothing already answered is asked twice. It refuses to overwrite an earlier label unless you pass --force (the old result is moved aside,
not deleted). Quota is per model per day: a measurement and its resume have to fit in it together (about 213 requests for 71 questions x 3 arms).
"""
import argparse
import contextlib
import json
import os
import re
import shutil
import sys
from datetime import datetime

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import BASE_DIR, settings                  # noqa: E402
from app.console import display_path, make_output_safe     # noqa: E402
from evals import bank, cost_run, runner                    # noqa: E402

LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def move_aside(path):
    """Move a file to `<name>.replaced-<time>.json` beside it and return the new name (evidence is never deleted)."""
    target = path[:-len(".json")] + f".replaced-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    runner.replace_file(path, target)
    return target


def load_prior(path):
    """The saved measurement to carry on, or None. The one at the label's path (a stopped run is saved there, a finished one too)."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


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
    parser.add_argument("--max-calls", type=int, default=400, help="stop before sending more than this many requests (default 400; a resume counts its own)")
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="change ONE setting for every arm (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="answer from a scripted stand-in for the provider: no quota, numbers are not measurements")
    parser.add_argument("--resume", action="store_true", help="carry on a stopped or partly failed measurement with the same label")
    parser.add_argument("--force", action="store_true", help="replace an earlier measurement with the same label (the old result is moved aside)")
    args = parser.parse_args(argv)
    make_output_safe()

    if not LABEL.fullmatch(args.label):
        print("Error: a label starts with a letter or a digit and has only letters, digits, dots, dashes and underscores (it names a folder).")
        return 1
    if args.resume and args.force:
        print("Error: --resume carries a measurement on and --force starts it again: pick one.")
        return 1
    if not args.dry_run and not args.model:
        print("Error: --model is required: name the model (not an alias like gemini-flash-lite-latest) so the result says what it measured.")
        return 1
    if args.max_calls < 1:
        print("Error: --max-calls must be 1 or more.")
        return 1
    try:
        arms = cost_run.parse_arms(args.arm or cost_run.DEFAULT_ARMS)
        shared = runner.parse_overrides(args.set)
        cases = runner.select_cases(args.only, base_only=True)          # the registered 41, whatever failures were converted since
        with runner.overridden(shared):
            base_strip = settings.context_strip_min_repeats
            embedding = settings.embed_provider
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    if base_strip and not all("context_strip_min_repeats" in overrides for _, overrides in arms):
        print(f"Error: CONTEXT_STRIP_MIN_REPEATS is already {base_strip} in your settings, so every arm that does not name it would strip too and nothing "
              "would be compared. Unset it (the arms say what they change), or name it in every arm.")
        return 1
    if args.dry_run and embedding != "local":
        print("Error: a dry run is free only with local embeddings (EMBED_PROVIDER=local); it will not spend API quota on embeddings.")
        return 1

    label = f"dry-{args.label}" if args.dry_run else args.label
    out_dir = os.path.join(cost_run.MEASURE_DIR, runner.safe_label(label))
    saved_path = os.path.join(out_dir, "cost-dry.json") if args.dry_run else cost_run.results_path(label)
    exists = os.path.exists(out_dir) or (not args.dry_run and cost_run.aggregate_exists(label))
    if args.resume and not os.path.exists(saved_path):
        print(f"Error: there is no saved measurement called {label!r} to resume ({display_path(saved_path, BASE_DIR)}).")
        return 1
    if exists and not args.force and not args.resume:
        print(f"Error: a measurement called {label!r} already exists. Use another --label, --resume to carry it on, or --force to replace it.")
        return 1

    questions = bank.sample(bank.load_questions(), args.bank, args.seed, exclude=[case["question"] for case in cases]) if args.bank else []
    items = cost_run.make_items(cases, questions)
    if args.limit:
        items = items[:args.limit]
    if not items:
        print("No questions selected.")
        return 1
    planned = len(items) * len(arms)
    if planned > args.max_calls and not args.resume:
        print(f"Error: {len(items)} questions x {len(arms)} arms is {planned} requests, over --max-calls {args.max_calls}. "
              f"Raise it, or narrow the questions with --only / --limit.")
        return 1

    model = args.model or "scripted-model"
    prior = load_prior(saved_path) if args.resume else None
    if prior and prior["meta"].get("complete") and not any(row["status"] == "error" for row in prior["rows"]):
        print(f"Nothing to resume: {label!r} is complete.")
        return 0
    with runner.overridden({**shared, **({"llm_rpm": 0} if args.dry_run else {})}):
        minutes = f", about {planned / settings.llm_rpm:.0f} minutes at {settings.llm_rpm} calls a minute" if settings.llm_rpm and not args.dry_run else ""
        print(("DRY RUN (scripted provider, no quota). " if args.dry_run else "") + f"{len(items)} questions x {len(arms)} arms "
              f"({', '.join(name for name, _ in arms)}) = {planned} requests{minutes}; model {model}; logs in {display_path(out_dir, BASE_DIR)}\n")
        try:
            if args.force:
                for old in (saved_path, saved_path[:-len(".json")] + ".incomplete.json"):
                    if os.path.exists(old) and not args.dry_run:      # a dry run's result sits in the folder that is removed below, and is worth nothing
                        print(f"The earlier result was moved aside to {display_path(move_aside(old), BASE_DIR)}.")
                if os.path.isdir(out_dir) and os.path.commonpath([out_dir, cost_run.MEASURE_DIR]) == cost_run.MEASURE_DIR and out_dir != cost_run.MEASURE_DIR:
                    shutil.rmtree(out_dir)                       # the raw logs of the measurement being replaced, nothing else
            elif prior:
                print(f"Resuming: {sum(1 for row in prior['rows'] if row['status'] != 'error')} answered requests are kept, "
                      f"{sum(1 for row in prior['rows'] if row['status'] == 'error')} failed ones are asked again.")
                print(f"The result being carried on was moved aside to {display_path(move_aside(saved_path), BASE_DIR)}.\n")

            def save(results):
                try:
                    cost_run.save_aggregate(results, saved_path)
                except OSError as exc:                           # a locked file must not end a run that has quota in it
                    print(f"  ! could not save ({type(exc).__name__}); carrying on, it will be tried again after the next question")

            with (cost_run.scripted_provider() if args.dry_run else contextlib.nullcontext()):
                results = cost_run.run(items, arms, label, model, out_dir, max_calls=args.max_calls, dry_run=args.dry_run, save=save, prior=prior)
        except (RuntimeError, ValueError) as exc:
            print(f"Error: {exc}")
            return 1

    print()
    print("\n".join(cost_run.format_summary(results)))
    print(f"\nsaved: {display_path(saved_path, BASE_DIR)}")
    return 0 if results["meta"]["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
