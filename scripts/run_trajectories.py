"""Week 8, mentor checks #1 and #3: grade the agent's PATH, not only its answer.

This runs the agent on the Week 7 tasks, then asks two questions of every run. Was the
ANSWER right (the rule checks)? And was the PATH right (did it use the tools the task needs, in a sensible
order, with inputs it was really given, and stop cleanly)? A run that is right by luck and wrong in its
path is the gap this week is about. It also reports what a run costs: mean and 99th percentile.

Run:
    python scripts/run_trajectories.py --label before                # runs the agent (model calls)
    python scripts/run_trajectories.py --label after --set agent_max_calls_per_tool=3
    python scripts/run_trajectories.py --interleave before after:agent_max_calls_per_tool=3 before-2 --repeats 3
    python scripts/run_trajectories.py --grade race-race             # re-grade a saved Week 7 race: free
    python scripts/run_trajectories.py --regrade before              # re-grade a saved run in place, keeping its settings: free
    python scripts/run_trajectories.py --show before                 # print the report of a saved run: free
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


def print_modes(graded):
    """The runs that showed a failure mode, with the evidence for each."""
    shown = [row for row in graded if row["modes"]]
    if shown:
        print("\nruns with a failure mode:")
        for row in shown:
            print(f"  {row['task_id']:<26} outcome {'right' if row['outcome_ok'] else 'WRONG'}  " +
                  "; ".join(f"{d['mode']} ({d['detail']})" for d in row["details"]))


def parse_arm(text):
    """'label' or 'label:NAME=VALUE,NAME=VALUE' into (label, settings that arm changes)."""
    label, _, changes = text.partition(":")
    if not label.strip():
        raise ValueError(f"an arm needs a label, got {text!r}")
    return label.strip(), runner.parse_overrides([part for part in changes.split(",") if part])


def run_interleaved(arms, tasks, repeats, common, options):
    """Run every arm on every task, one run of each arm before the next task, repeat by repeat.

    Running arm A to the end and then arm B means a daily quota that runs out leaves B empty, and
    the provider may be slower or faster for B than it was for A. Interleaving gives each arm the same conditions
    and, if the quota ends part-way, almost the same number of runs. The arm order rotates so no arm always goes
    first. Returns [(label, records, meta)], one per arm.
    """
    records, base_meta, stopped = {label: [] for label, _ in arms}, None, None
    for repeat in range(1, repeats + 1):
        for index, task in enumerate(tasks):
            turn = (repeat + index) % len(arms)
            for label, changes in arms[turn:] + arms[:turn]:
                with runner.overridden(dict(common, **changes)):
                    run = race.run_race([task], approaches=("agent",), repeats=1, label=label, **options,
                                        say=lambda text, label=label, repeat=repeat: print(
                                            f"  {label:<16}{text.replace('run 1/1', f'repeat {repeat}/{repeats}')}"))
                base_meta = base_meta or run["meta"]
                for record in run["runs"]:
                    records[label].append(dict(record, repeat=repeat))
                if not run["meta"]["complete"]:
                    stopped = run["meta"]["stopped_because"]
                    break
            if stopped:
                break
        if stopped:
            break
    labels = [label for label, _ in arms]
    return [(label, records[label],
             dict(base_meta or {}, label=label, repeats=repeats, tasks=[t["id"] for t in tasks], overrides=dict(common, **changes),
                  defense=bool(options), complete=stopped is None, stopped_because=stopped,
                  interleaved_with=[other for other in labels if other != label]))
            for label, changes in arms]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the agent on the tasks and grade each run's path.")
    parser.add_argument("--label", default="agent", help="name of this run (default: agent)")
    parser.add_argument("--repeats", type=int, default=2, help="runs per task (default 2)")
    parser.add_argument("--only", nargs="+", metavar="ID", help="only these task ids")
    parser.add_argument("--set", dest="overrides", action="append", metavar="NAME=VALUE", help="change one setting for this run")
    parser.add_argument("--defense", action="store_true", help="run with the three defence layers on")
    parser.add_argument("--grade", metavar="LABEL_OR_PATH", help="re-grade a saved race or trajectory file instead of running")
    parser.add_argument("--interleave", nargs="+", metavar="LABEL[:NAME=VALUE,..]",
                        help="run several arms side by side, one run of each arm per task and repeat, each saved under its own label "
                             "(for example: before after:agent_max_calls_per_tool=3 before-2)")
    parser.add_argument("--show", metavar="LABEL", help="print the report of a saved trajectory run (no model calls, nothing saved)")
    parser.add_argument("--regrade", metavar="LABEL", help="grade a saved trajectory run again with today's rules, in place (no model calls; "
                                                           "its runs, settings and completeness are kept)")
    args = parser.parse_args(argv)
    make_output_safe()

    if args.show:
        try:
            saved = runner.load_results("trajectories-" + args.show)
        except FileNotFoundError as exc:
            print(f"Error: {exc}")
            return 1
        meta = saved["meta"]
        if not meta.get("complete", True):
            print(f"(a PARTIAL run: it stopped early, {meta.get('stopped_because') or 'no reason recorded'})\n")
        print("\n".join(trajectory.format_report(saved["summary"], args.show)))
        print_modes(saved["graded"])
        return 0

    if args.regrade:
        try:
            saved = runner.load_results("trajectories-" + args.regrade)
        except FileNotFoundError as exc:
            print(f"Error: {exc}")
            return 1
        note = "graded again by the rules in this checkout; the runs and settings are unchanged"
        results, path = grade_and_save(get_tasks(None, include_probes=True), saved["runs"], dict(saved["meta"], regraded=note), args.regrade)
        old, new = saved.get("summary", {}), results["summary"]
        print("\n".join(trajectory.format_report(new, args.regrade)))
        print_modes(results["graded"])
        print(f"\nre-graded in place. As saved -> now:  trajectory clean {old.get('trajectory_ok')} -> {new['trajectory_ok']},  "
              f"outcome right {old.get('outcome_ok')} -> {new['outcome_ok']},  modes {old.get('modes')} -> {new['modes']}")
        print(f"saved: {display_path(path, BASE_DIR)}")
        return 0

    if args.interleave:
        try:
            arms = [parse_arm(text) for text in args.interleave]
            if len(arms) < 2 or len({label for label, _ in arms}) != len(arms):
                raise ValueError("--interleave needs two or more arms with different labels")
            if args.repeats < 1:
                raise ValueError(f"--repeats must be 1 or greater, got {args.repeats}")
            common, tasks = runner.parse_overrides(args.overrides), get_tasks(args.only, include_probes=True)
            pipeline.require_index()
            options = {"defense": Defense(trusted_contacts=injection.trusted_contacts(), system_prompt=loop.SYSTEM_PROMPT)} if args.defense else {}
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            print(f"Error: {exc}")
            return 1
        print(f"Interleaving {len(arms)} arms ({', '.join(label for label, _ in arms)}) over {len(tasks)} task(s) x {args.repeats} "
              f"on {settings.llm_model}, defences {'ON' if args.defense else 'off'}\n")
        saved_all = True
        for label, records, meta in run_interleaved(arms, tasks, args.repeats, common, options):
            saved_all = saved_all and meta["complete"]
            if not records:
                print(f"\n'{label}': no run finished, nothing saved")
                continue
            results, path = grade_and_save(tasks, records, meta, label)
            print()
            print("\n".join(trajectory.format_report(results["summary"], label)))
            print_modes(results["graded"])
            print(f"\nsaved: {display_path(path, BASE_DIR)}")
        return 0 if saved_all else 1

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
    print_modes(results["graded"])
    print(f"\nsaved: {display_path(path, BASE_DIR)}")
    return 0 if meta.get("complete", True) else 1


if __name__ == "__main__":
    sys.exit(main())
