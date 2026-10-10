"""Week 7, mentor checks #3 and #4: race the agent against the fixed workflow, with real numbers.

The same tasks, several times each, once with the agent and once with the fixed
workflow, scored by the same rule checks. The table shows reliability (how often it got it right),
cost (model calls and tokens) and speed (seconds inside model calls). Which one you would ship, and
why, is your call to write: this prints the evidence for it.

Run:
    python scripts/race_agent.py                      # every task, 3 runs each, both approaches
    python scripts/race_agent.py --repeats 5
    python scripts/race_agent.py --only t7-notice-end-date t7-unanswerable
    python scripts/race_agent.py --save               # also write docs/week7/race-results.md

In the committed race an agent run took 3.5 model calls on average and a workflow run exactly 1, so the
default race (9 tasks x 3 repeats x 2 approaches) is about 120 calls. It throttles to LLM_RPM and stops with
a clear message if a daily quota runs out, keeping what finished.

A new race is saved under its own --label. Racing again without a label would overwrite the committed
`race` results, so use a new one (for example --label rerun) when you repeat it.
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import BASE_DIR, settings                    # noqa: E402
from app.console import display_path, make_output_safe       # noqa: E402
from app.rag import pipeline                                 # noqa: E402
from evals import race, runner                               # noqa: E402
from evals.agent_tasks import get_tasks                      # noqa: E402


def save_markdown(lines, command):
    """Write the numbers to docs/week7/race-results.md, naming the command that regenerates them."""
    out_path = os.path.join(BASE_DIR, "docs", "week7", "race-results.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write("# Week 7: the race (generated)\n\n")
        handle.write(f"Generated {datetime.now().isoformat(timespec='seconds')} by `{command}`. "
                     "Numbers only: which approach to ship, and why, is yours to write in `findings.md`.\n\n")
        handle.write("```\n" + "\n".join(lines) + "\n```\n")
    print(f"saved: {display_path(out_path, BASE_DIR)}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Race the agent against the fixed workflow.")
    parser.add_argument("--label", default="race", help="name of this race (default: race)")
    parser.add_argument("--repeats", type=int, default=3, help="runs per task and approach (default 3)")
    parser.add_argument("--only", nargs="+", metavar="ID", help="race only these task ids")
    parser.add_argument("--approaches", nargs="+", choices=race.APPROACHES, default=list(race.APPROACHES))
    parser.add_argument("--save", action="store_true", help="also write docs/week7/race-results.md")
    parser.add_argument("--show", metavar="LABEL", help="print the summary of a saved race (no model calls) instead of racing")
    parser.add_argument("--rescore", action="store_true",
                        help="with --show: re-score the saved runs against the current task definitions and list what changed")
    args = parser.parse_args(argv)
    make_output_safe()

    if args.show:
        try:
            saved = runner.load_results("race-" + args.show)
        except FileNotFoundError as exc:
            print(f"Error: {exc}")
            return 1
        lines = race.format_summary(saved)
        command = f"python scripts/race_agent.py --show {args.show}" + (" --rescore" if args.rescore else "") + (" --save" if args.save else "")
        if args.rescore:
            rescored = race.rescore(saved)
            changed = rescored["meta"]["rescored_changes"]
            lines = ["AS RACED (the checks as they were when the race ran):", ""] + lines
            lines += ["", "=" * 78, "RE-SCORED with the current checks and tasks (same runs, same answers, no model calls):", ""]
            lines += race.format_summary(rescored)
            lines += ["", f"{len(changed)} run(s) changed result:"]
            lines += [f"  {c['task_id']:<24}{c['approach']:<10}run {c['repeat']}  {'pass' if c['was'] else 'FAIL'} -> {'pass' if c['now'] else 'FAIL'}"
                      for c in changed]
        print("\n".join(lines))
        if args.save:
            save_markdown(lines, command)
        return 0

    if args.repeats < 1:
        print(f"Error: --repeats must be 1 or greater, got {args.repeats}.")
        return 1
    try:
        pipeline.require_index()
        tasks = get_tasks(args.only)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1

    runs = len(tasks) * args.repeats * len(args.approaches)
    print(f"Racing {len(tasks)} task(s) x {args.repeats} run(s) x {len(args.approaches)} approach(es) = {runs} runs "
          f"on {settings.llm_model} (limits: {settings.agent_max_steps} steps, {settings.agent_max_total_tokens} tokens, "
          f"{settings.agent_timeout_seconds:.0f}s per agent run)\n")
    results = race.run_race(tasks, approaches=tuple(args.approaches), repeats=args.repeats, label=args.label)
    path = runner.save_results(results, runner.results_path("race-" + args.label))

    print()
    lines = race.format_summary(results)
    for line in lines:
        print(line)
    print(f"\nsaved: {display_path(path, BASE_DIR)}")

    if args.save:
        save_markdown(lines, f"python scripts/race_agent.py --label {args.label} --repeats {args.repeats} --save")
    return 0 if results["meta"]["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
