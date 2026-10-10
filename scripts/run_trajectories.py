"""Week 8, mentor checks #1 and #3: grade the agent's PATH, not only its answer.

This runs the agent on the Week 7 tasks, then asks two questions of every run. Was the
ANSWER right (the rule checks)? And was the PATH right (did it use the tools the task needs, in a sensible
order, with inputs it was really given, and stop cleanly)? A run that is right by luck and wrong in its
path is the gap this week is about. It also reports what a run costs: mean and 99th percentile.

Run:
    python scripts/run_trajectories.py --label before                # runs the agent (model calls)
    python scripts/run_trajectories.py --label after --set agent_verify=true
    python scripts/run_trajectories.py --grade race-race             # re-grade a saved Week 7 race: free
    python scripts/run_trajectories.py --label guarded --defense     # same tasks with the defences on
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent import loop                                   # noqa: E402
from app.agent.defense import Defense                        # noqa: E402
from app.config import BASE_DIR, settings                    # noqa: E402
from app.console import display_path, make_output_safe       # noqa: E402
from app.rag import pipeline                                 # noqa: E402
from evals import injection, race, runner, trajectory        # noqa: E402
from evals.agent_tasks import get_tasks                      # noqa: E402


def grade_and_save(tasks, records, meta, label):
    graded = trajectory.grade_all(records, tasks)
    summary = trajectory.summarize(graded, [r for r in records if r["task_id"] in {t["id"] for t in tasks}])
    results = {"meta": meta, "runs": records, "graded": graded, "summary": summary}
    return results, runner.save_results(results, runner.results_path("trajectories-" + label))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the agent on the tasks and grade each run's path.")
    parser.add_argument("--label", default="agent", help="name of this run (default: agent)")
    parser.add_argument("--repeats", type=int, default=2, help="runs per task (default 2)")
    parser.add_argument("--only", nargs="+", metavar="ID", help="only these task ids")
    parser.add_argument("--set", dest="overrides", action="append", metavar="NAME=VALUE", help="change one setting for this run")
    parser.add_argument("--defense", action="store_true", help="run with the three defence layers on")
    parser.add_argument("--grade", metavar="LABEL_OR_PATH", help="re-grade a saved race or trajectory file instead of running")
    args = parser.parse_args(argv)
    make_output_safe()

    try:
        overrides = runner.parse_overrides(args.overrides)
        tasks = get_tasks(args.only, include_probes=True)
        if args.grade:
            saved = runner.load_results(args.grade)
            records = [r for r in saved["runs"] if r.get("approach", "agent") == "agent"]
            meta = {"label": args.label, "regraded_from": args.grade, "complete": True}
        else:
            if args.repeats < 1:
                raise ValueError(f"--repeats must be 1 or greater, got {args.repeats}")
            pipeline.require_index()
            options = {"defense": Defense(trusted_contacts=injection.trusted_contacts(), system_prompt=loop.SYSTEM_PROMPT)} if args.defense else {}
            print(f"Running {len(tasks)} task(s) x {args.repeats} on {settings.llm_model}, settings changed: {overrides or 'none'}, "
                  f"defences {'ON' if args.defense else 'off'}\n")
            with runner.overridden(overrides):
                run = race.run_race(tasks, approaches=("agent",), repeats=args.repeats, label=args.label, **options)
            records, meta = run["runs"], dict(run["meta"], overrides=overrides, defense=args.defense)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"Error: {exc}")
        return 1

    results, path = grade_and_save(tasks, records, meta, args.label)
    print()
    print("\n".join(trajectory.format_report(results["summary"], args.label)))
    shown = [row for row in results["graded"] if row["modes"]]
    if shown:
        print("\nruns with a failure mode:")
        for row in shown:
            print(f"  {row['task_id']:<26} outcome {'right' if row['outcome_ok'] else 'WRONG'}  " +
                  "; ".join(f"{d['mode']} ({d['detail']})" for d in row["details"]))
    print(f"\nsaved: {display_path(path, BASE_DIR)}")
    return 0 if meta.get("complete", True) else 1


if __name__ == "__main__":
    sys.exit(main())
