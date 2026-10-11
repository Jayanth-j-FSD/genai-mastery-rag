"""Week 10, mentor checks #1 to #3: race the team against the single agent on the SAME tasks, and print the four numbers.

The same nine tasks, the same model, the same rule checks and the same limits on tokens and time, run once
as the single agent and once as the team (a manager and two specialists), several times each. The report gives quality,
speed, tokens and cost for both, so a verdict about which design to use, and why, can rest on numbers even if the team
lost. The verdict itself is yours to write; this prints the evidence.

The runs are interleaved: repeat by repeat, task by task, one run of every arm before the next task, with the arm order
rotating. If a free-tier quota ends the race part-way, every arm has almost the same runs, and the provider's mood at any
hour is shared by all of them. `--noise` adds a second, identical single-agent arm (`agent-2`) that calibrates the method.

Before a race counts it is frozen: the code and prompts are committed (a race refuses an uncommitted tree; only a pilot,
whose label starts with `pilot-`, may run on one), every result records the git commit and a hash of the code, prompts,
checks, tasks and corpus it ran with, and a race cannot be resumed after any of them changed.

Run:
    python scripts/race_team.py --plan                                              # requests a race would take: no model calls
    python scripts/race_team.py --label wk10 --model gemini-3.5-flash-lite           # agent against team, 9 tasks x 3 repeats (model calls)
    python scripts/race_team.py --label wk10 --model gemini-3.5-flash-lite --noise   # plus the calibration arm
    python scripts/race_team.py --label wk10 --model gemini-3.5-flash-lite --resume  # carry on a race that stopped early (a quota)
    python scripts/race_team.py --show wk10                                          # print the report of a saved race: free
    python scripts/race_team.py --show wk10 --price-in 0.10 --price-out 0.40 --price-source "where you read them"   # dollars: free
    python scripts/race_team.py --show wk10 --rescore                                # score the saved answers with today's checks: free
    python scripts/race_team.py --show wk10 --save                                   # also write docs/week10/race-results.md

A saved label is evidence and is never replaced silently: racing again under it stops with a message unless you pass --resume
(carry on) or --force (start over; an older complete race is kept if the new one is cut short). Name the model: never the alias.
"""
import argparse
import hashlib
import inspect
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openai                                                # noqa: E402
from app import llm                                          # noqa: E402
from app.agent import loop, team, tools as agent_tools, workflow     # noqa: E402
from app.agent.tools import default_tools                    # noqa: E402
from app.config import BASE_DIR, settings                    # noqa: E402
from app.console import display_path, make_output_safe       # noqa: E402
from app.rag import pipeline                                 # noqa: E402
from evals import race, runner, team_report                  # noqa: E402
from evals.agent_tasks import get_tasks                      # noqa: E402

BASE = {"agent": "agent", "team": "team", "agent-2": "agent", "workflow": "workflow"}      # what each arm label runs
STAMPED_FILES = ("app/agent/team.py", "app/agent/loop.py", "app/llm.py", "evals/checks.py", "evals/agent_tasks.py", "evals/race.py",
                 "evals/team_prediction.py")                                              # hashed into every result
DEFAULT_TIMEOUT = 300.0        # seconds a run may take: wider than the 120 s default because the free tier's rate-limit pauses count, for BOTH arms
CODE_KEYS = tuple(os.path.basename(path) for path in STAMPED_FILES)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def file_sha(relative_path):
    """The first 12 hex digits of a file's hash with line endings normalised, so a Windows checkout hashes like a Linux one."""
    try:
        with open(os.path.join(BASE_DIR, relative_path), "rb") as handle:
            return hashlib.sha256(handle.read().replace(b"\r\n", b"\n")).hexdigest()[:12]
    except OSError:
        return None


def git(*args):
    """The output of one git command in the project, or None when git is missing or the command fails."""
    try:
        out = subprocess.run(["git", *args], cwd=BASE_DIR, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def code_stamp():
    """Which code ran: the git commit, whether code under app, evals or scripts had uncommitted changes, and a hash of each file that matters."""
    status = git("status", "--porcelain", "--", "app", "evals", "scripts")
    stamp = {"git": git("rev-parse", "--short", "HEAD") or "unknown", "dirty": None if status is None else bool(status)}
    stamp.update({os.path.basename(path): file_sha(path) for path in STAMPED_FILES})
    return stamp


def corpus_fingerprint():
    """Every document the index is built from, with a hash of its bytes: the evidence that both arms read the same corpus."""
    files = {}
    for name in sorted(os.listdir(settings.corpus_dir)) if os.path.isdir(settings.corpus_dir) else []:
        path = os.path.join(settings.corpus_dir, name)
        if os.path.isfile(path) and not name.startswith("."):
            with open(path, "rb") as handle:
                files[name] = hashlib.sha256(handle.read()).hexdigest()[:12]
    return files


def scrub_text(text, limit=300):
    """Text that may reach a tracked file: the API key and the project's path replaced, and cut short."""
    text = str(text)
    key = settings.openai_api_key
    if key and len(key) >= 8:
        text = text.replace(key, "<key>")
    base = str(BASE_DIR)                                              # a Path in the app, a str in tests: Path.replace would RENAME a file
    for prefix in {base, base.replace("\\", "/")}:
        text = text.replace(prefix, "<project>")
    return text[:limit]


def scrub_record(record):
    """Provider error text in a run's steps is cut and scrubbed before it can be saved in a public repo."""
    for step in record.get("steps") or []:
        if step.get("kind") == "error":
            step["content"] = scrub_text(step.get("content", ""))
    return record


def arm_list(noise=False, with_workflow=False):
    return ["agent", "team"] + ([team_report.NOISE] if noise else []) + (["workflow"] if with_workflow else [])


def build_plan(tasks, repeats, arms):
    """[(repeat, task, arm)] in running order: repeat by repeat, task by task, every arm once per task, the arm order rotating.

    Repeat-major on purpose: if a quota ends the race, every task has fewer repeats instead of the last tasks having none.
    """
    plan = []
    for repeat in range(1, repeats + 1):
        for index, task in enumerate(tasks):
            turn = (repeat + index) % len(arms)
            plan.extend((repeat, task, arm) for arm in arms[turn:] + arms[:turn])
    return plan


def tools_note(names):
    available = {tool.name: tool for tool in default_tools()}
    return ", ".join(f"{name} {sha(available[name].description)}" for name in names)


def arm_config(arm, timeout=DEFAULT_TIMEOUT):
    """What this arm was run with, so a reader can see that the arms differ only where they are meant to."""
    shared = {"memory": "on", "calls per tool cap": 0, "timeout": f"{timeout:g}s"}
    if arm in ("agent", team_report.NOISE):
        return {**shared, "max steps": settings.agent_max_steps, "prompt sha": sha(loop.SYSTEM_PROMPT),
                "tools": tools_note(["search_policies", "calculate", "add_days"])}
    if arm == "team":
        specialists = team.SPECIALISTS
        return {**shared, "manager steps": settings.agent_max_steps, **{f"{name} steps": spec["max_steps"] for name, spec in specialists.items()},
                "manager prompt sha": sha(team.MANAGER_PROMPT), **{f"{name} prompt sha": sha(spec["prompt"]) for name, spec in specialists.items()},
                "hand-off tools": ", ".join(f"{spec['tool']} {sha(spec['description'])}" for spec in specialists.values()),
                **{f"{name} tools": tools_note(spec["skills"]) for name, spec in specialists.items()}}
    return {"retrieves": workflow.DEFAULT_TOP_K, "prompt sha": sha(workflow.WORKFLOW_PROMPT)}


def caps_table(arms, timeout=DEFAULT_TIMEOUT):
    """What each agent may use, one row per agent per arm: the step limit is per agent, the token and time budgets are the run's."""
    rows = []
    for arm in arms:
        if arm == "team":
            rows.append({"arm": arm, "agent": "manager", "steps": settings.agent_max_steps, "tokens": "shared", "timeout": "shared"})
            rows += [{"arm": arm, "agent": name, "steps": spec["max_steps"], "tokens": "shared", "timeout": "shared"} for name, spec in team.SPECIALISTS.items()]
        elif arm == "workflow":
            rows.append({"arm": arm, "agent": "workflow", "steps": 2, "tokens": "n/a", "timeout": "n/a"})
        else:
            rows.append({"arm": arm, "agent": "agent", "steps": settings.agent_max_steps, "tokens": settings.agent_max_total_tokens, "timeout": f"{timeout:g}s"})
    for row in rows:
        row["calls per tool"], row["memory"] = 0, "on" if row["arm"] != "workflow" else "n/a"
    return rows


def make_meta(label, tasks, repeats, arms, model, started, timeout=DEFAULT_TIMEOUT):
    return {"label": label, "started": started, "complete": False, "stopped_because": None, "repeats": repeats,
            "approaches": list(arms), "arms": list(arms), "tasks": [task["id"] for task in tasks], "interleaved": True,
            "models": {arm: model for arm in arms}, "noise_arm": team_report.NOISE if team_report.NOISE in arms else None,
            "limits": {"max_steps": settings.agent_max_steps, "max_total_tokens": settings.agent_max_total_tokens, "timeout_seconds": timeout,
                       "agent_max_calls_per_tool": 0},
            "llm_rpm": settings.llm_rpm, "retrieval_mode": settings.retrieval_mode,
            "search": {"top_k default": inspect.signature(agent_tools.search_policies).parameters["top_k"].default,
                       "passage chars": agent_tools._MAX_PASSAGE_CHARS, "retrieval mode": settings.retrieval_mode},
            "config": {arm: arm_config(arm, timeout) for arm in arms}, "caps": caps_table(arms, timeout),
            "code": code_stamp(), "corpus": corpus_fingerprint(), "resumed": []}


def provider_trouble(record):
    """A run that ended on a provider error, either the manager's own or a specialist's (which the manager then had to work around)."""
    handoffs = (record.get("team") or {}).get("handoffs", [])
    return record["stop_reason"] == "error" or any(handoff.get("stop_reason") == "error" for handoff in handoffs)


def usage_cross_check(record, scope):
    """None when the per-call records add up to what the run reported, else a sentence saying how they differ.
    Skipped when the scope saw no calls at all (nothing to compare)."""
    counted = scope.totals(deep=True)
    if not scope.walk():
        return None
    reported = (record["llm_calls"], record["prompt_tokens"], record["completion_tokens"])
    seen = (counted["calls"], counted["prompt_tokens"], counted["completion_tokens"])
    if seen == reported:
        return None
    return (f"usage mismatch: the per-call records add up to {seen[0]} calls and {seen[1] + seen[2]} tokens, but the run reported "
            f"{reported[0]} calls and {reported[1] + reported[2]} tokens")


def run_scoped(arm, task, repeat, tools, options, run_one):
    """One run inside a call scope, so every arm is measured by the same per-call instrument."""
    with llm.call_scope(arm) as scope:
        record = run_one(task, BASE[arm], repeat, tools, **options)
    if not record.get("team"):                     # the team keeps its own, tagged by agent
        record["call_log"] = [dict(call, agent=arm, handoff=None) for _scope, call in scope.walk()]
        warning = usage_cross_check(record, scope)
        if warning:
            record["usage_warning"] = warning
    return scrub_record(record)


def run_plan(plan, results, tools, options, save, say=print, run_one=None, max_calls=None):
    """Run what the plan lists and the results do not have yet, saving after every run. Stops, keeping what finished, when a
    quota runs out, when MAX_ERRORS_IN_A_ROW runs in a row hit a provider error, when a run crashes, when a run's usage does
    not add up or a hand-off failed on a bug, or when --max-calls model calls have been used. Returns the reason, or None."""
    run_one = run_one or race.run_one
    done = {(run["repeat"], run["task_id"], run["approach"]) for run in results["runs"]}
    repeats, errors_in_a_row, calls_used = results["meta"]["repeats"], 0, 0
    for repeat, task, arm in plan:
        if (repeat, task["id"], arm) in done:
            continue
        if max_calls is not None and calls_used >= max_calls:
            return f"--max-calls {max_calls} reached ({calls_used} model calls used in this session)"
        llm.reset_last_model()                                         # so a run that never got an answer does not borrow the last one's name
        try:
            record = run_scoped(arm, task, repeat, tools, options, run_one)
        except llm.QuotaExhausted as exc:
            return scrub_text(exc)
        except openai.OpenAIError as exc:
            return scrub_text(f"the provider failed ({type(exc).__name__}): {exc}")
        except Exception as exc:                                       # a crash in one run must not lose the runs that finished
            return scrub_text(f"a run failed unexpectedly ({type(exc).__name__}): {exc}")
        record["approach"] = arm
        record["served_model"] = llm.last_model()                      # what the provider says answered (an alias can move)
        results["runs"].append(record)
        save(results)
        calls_used += record["llm_calls"]
        say(f"[{'ok  ' if record['success'] else 'FAIL'}] {task['id']:<24} {arm:<9} repeat {repeat}/{repeats}  "
            f"{record['llm_calls']} call(s), {record['prompt_tokens'] + record['completion_tokens']} tokens, {record['stop_reason']}")
        crew = record.get("team") or {}
        if record.get("usage_warning") or crew.get("warnings"):
            return scrub_text(f"a run's per-agent usage did not add up to the process counters: {record.get('usage_warning') or crew['warnings'][0]}")
        if crew.get("errors"):
            return f"a hand-off failed on a bug in the team code ({crew['errors'][0]['type']} in the {crew['errors'][0]['agent']}); fix it and race again"
        errors_in_a_row = errors_in_a_row + 1 if provider_trouble(record) else 0
        if errors_in_a_row >= race.MAX_ERRORS_IN_A_ROW:                 # one provider error is a run; a string of them is an outage
            steps = record.get("steps") or [{}]
            return scrub_text(f"{errors_in_a_row} runs in a row ended on a provider error (the last: {steps[-1].get('content') or 'no detail recorded'})")
    return None


def estimate_team_calls(saved):
    """Model calls per run a team WOULD make on the tool mix a saved single-agent race used: (lean, high). An estimate from a
    model of the hand-offs, not a measurement: lean = one hand-off per specialist that was needed, high = one per tool call."""
    lean, high, runs = 0, 0, 0
    for run in saved["runs"]:
        if run["approach"] != "agent":
            continue
        searches = sum(name == "search_policies" for name in run["tool_calls"])
        calculations = sum(name in ("calculate", "add_days") for name in run["tool_calls"])
        handoffs = (searches > 0) + (calculations > 0)
        lean += (handoffs + 1) + ((searches + 1) if searches else 0) + ((calculations + 1) if calculations else 0)
        every = searches + calculations
        high += (every + 1) + 2 * every
        runs += 1
    return (lean / runs, high / runs) if runs else (None, None)


def plan_lines(arms, tasks, repeats, saved, pilot=None):
    """What a race would take, in requests and minutes, from saved numbers. Printed before any model call."""
    runs = len(tasks) * repeats
    agent_per_run = mean_calls(saved, "agent")
    lean, high = estimate_team_calls(saved) if saved else (None, None)
    rows = {"agent": agent_per_run, "agent-2": agent_per_run, "workflow": 1.0}
    saved_runs = sum(run["approach"] == "agent" for run in (saved or {"runs": []})["runs"])
    lines = [f"plan: {len(arms)} arm(s) ({', '.join(arms)}) x {len(tasks)} task(s) x {repeats} repeat(s) = {runs * len(arms)} runs",
             f"single agent: {agent_per_run:.1f} model calls a run, measured over {saved_runs} runs of the saved Week 7 race" if agent_per_run else
             "single agent: no saved race to measure from"]
    if pilot and pilot.get("team"):
        lines.append(f"team: {pilot['team']:.1f} model calls a run, measured on {pilot['n']} pilot question(s) that are not race tasks "
                     f"(the single agent made {pilot['agent']:.1f} on the same)")
        rows["team"] = pilot["team"]
    elif lean:
        lines.append(f"team: between {lean:.1f} and {high:.1f} model calls a run (an ESTIMATE from a model of the hand-offs on that race's tool mix, not a measurement)")
        rows["team"] = (lean + high) / 2
    total = sum(rows.get(arm, 0) * runs for arm in arms)
    lines.append(f"about {total:.0f} model calls in all" + (f", {total / settings.llm_rpm:.0f} minutes at {settings.llm_rpm} calls a minute" if settings.llm_rpm else "")
                 + ". A lite model's free key allowed about 500 requests a model a day when measured, and retries count against it: "
                   "give the race a model nothing else is using that day, and set --max-calls below the cap.")
    return lines


def mean_calls(saved, approach):
    rows = [run["llm_calls"] for run in (saved or {"runs": []})["runs"] if run["approach"] == approach]
    return sum(rows) / len(rows) if rows else 0.0


def pilot_numbers(path_or_label):
    """Calls per run for each arm of a saved pilot (scripts/pilot_team.py), or None when there is none."""
    try:
        saved = runner.load_results(path_or_label)
    except FileNotFoundError:
        return None
    team_runs = [run for run in saved["runs"] if run["arm"] == "team"]
    agent_runs = [run for run in saved["runs"] if run["arm"] == "agent"]
    if not team_runs or not agent_runs:
        return None
    return {"team": sum(run["calls"] for run in team_runs) / len(team_runs), "agent": sum(run["calls"] for run in agent_runs) / len(agent_runs),
            "n": len(team_runs)}


def save_markdown(lines, command):
    """Write the report to docs/week10/race-results.md, naming the command that prints it again."""
    doc_path = os.path.join(BASE_DIR, "docs", "week10", "race-results.md")
    os.makedirs(os.path.dirname(doc_path), exist_ok=True)
    with open(doc_path, "w", encoding="utf-8") as handle:
        handle.write("# Week 10: the race (generated)\n\n")
        handle.write(f"Printed by `{command}` from the saved runs, with no model calls. Numbers only: the verdict about which design to "
                     "use, and why, is yours to write in `findings.md`.\n\n")
        handle.write("```\n" + "\n".join(lines) + "\n```\n")
    print(f"saved: {display_path(doc_path, BASE_DIR)}")


def prices_from(args):
    """(input, output, source) from the flags: both prices or neither, and a source for them. Zero means 'none stated': the report
    never falls back to a PRICE setting, so a stale .env value cannot put dollars into a saved report."""
    if (args.price_in is None) != (args.price_out is None):
        raise ValueError("state both --price-in and --price-out, or neither")
    if args.price_in is not None and not (args.price_source or "").strip():
        raise ValueError("say where the prices came from with --price-source TEXT: a price without its source is not evidence")
    if args.price_source and args.price_in is None:
        raise ValueError("--price-source goes with --price-in and --price-out")
    return (args.price_in or 0.0), (args.price_out or 0.0), args.price_source


def show(args):
    try:
        saved = runner.load_results("race-" + args.show)
        price_in, price_out, source = prices_from(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1
    lines = team_report.format_report(saved, price_in, price_out, source)
    command = f"python scripts/race_team.py --show {args.show}" + (f" --price-in {args.price_in} --price-out {args.price_out} "
                                                                  f"--price-source \"{source}\"" if source else "") + (" --rescore" if args.rescore else "")
    if args.rescore:
        rescored = race.rescore(saved)
        changed = rescored["meta"]["rescored_changes"]
        lines = ["AS RACED (the rule checks as they were when the race ran):", ""] + lines
        lines += ["", "=" * 78, "RE-SCORED with today's rule checks (same runs, same answers, no model calls):", ""]
        lines += team_report.format_report(rescored, price_in, price_out, source)
        lines += ["", f"{len(changed)} run(s) changed result:"]
        lines += [f"  {c['task_id']:<24}{c['approach']:<9}run {c['repeat']}  {'pass' if c['was'] else 'FAIL'} -> {'pass' if c['now'] else 'FAIL'}" for c in changed]
    print("\n".join(lines))
    if args.save:
        save_markdown(lines, command + " --save")
    return 0


def changed_since(saved_meta, meta):
    """What differs between a saved race and the one about to carry it on: anything that would make the two halves not one race."""
    differences = []
    for key in ("tasks", "repeats", "models", "limits", "retrieval_mode", "search", "corpus"):
        if saved_meta.get(key) != meta.get(key):
            differences.append(key)
    saved_code, code = saved_meta.get("code") or {}, meta["code"]
    differences += [key for key in CODE_KEYS if saved_code.get(key) != code.get(key)]
    for arm, setting in (saved_meta.get("config") or {}).items():
        if meta["config"].get(arm) != setting:
            differences.append(f"config of {arm}")
    return differences


def main(argv=None):
    parser = argparse.ArgumentParser(description="Race the team against the single agent on the same tasks.")
    parser.add_argument("--label", default=None, help="name of this race (saved as evals/results/race-<label>.json)")
    parser.add_argument("--repeats", type=int, default=3, help="runs per task and arm (default 3)")
    parser.add_argument("--only", nargs="+", metavar="ID", help="race only these task ids")
    parser.add_argument("--noise", action="store_true", help="add a second identical single-agent arm (agent-2): a calibration of the method")
    parser.add_argument("--workflow", action="store_true", help="add the fixed workflow as a reference arm (one model call a run)")
    parser.add_argument("--model", default=None, help="chat model for every arm, by its exact name (required to race: an alias can move)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help=f"seconds a run may take, for every arm (default {DEFAULT_TIMEOUT:g})")
    parser.add_argument("--max-calls", type=int, default=None, help="stop after this many model calls in this session (keep it below the day's quota)")
    parser.add_argument("--plan", action="store_true", help="print what the race would take in requests and minutes, then stop (no model calls)")
    parser.add_argument("--pilot", metavar="LABEL", default=None, help="with --plan: a saved pilot whose calls per run replace the estimate")
    parser.add_argument("--allow-dirty", action="store_true", help="race on an uncommitted tree: only for a label that starts with pilot-")
    parser.add_argument("--resume", action="store_true", help="carry on a saved race that stopped early, under the same label")
    parser.add_argument("--force", action="store_true", help="start over under a label that is already saved")
    parser.add_argument("--show", metavar="LABEL", help="print the report of a saved race (no model calls) instead of racing")
    parser.add_argument("--price-in", type=float, default=None, help="with --show: dollars per million INPUT tokens, a price you state")
    parser.add_argument("--price-out", type=float, default=None, help="with --show: dollars per million OUTPUT tokens, a price you state")
    parser.add_argument("--price-source", default=None, help="with --show: where you read those prices and when (required with them)")
    parser.add_argument("--rescore", action="store_true", help="with --show: score the saved answers with the current rule checks and list what changed")
    parser.add_argument("--save", action="store_true", help="with --show: also write docs/week10/race-results.md")
    args = parser.parse_args(argv)
    make_output_safe()

    for flag, value in (("--price-in", args.price_in), ("--price-out", args.price_out)):
        if value is not None and value < 0:
            print(f"Error: {flag} must be 0 or more, got {value}.")
            return 1
    if args.show:
        return show(args)
    for flag, used in (("--price-in", args.price_in is not None), ("--price-out", args.price_out is not None), ("--price-source", bool(args.price_source)),
                       ("--rescore", args.rescore), ("--save", args.save)):
        if used:                                        # silently ignored, they would look like they had worked
            print(f"Error: {flag} works on a saved race, so it needs --show LABEL.")
            return 1
    if args.repeats < 1 or args.timeout <= 0 or (args.max_calls is not None and args.max_calls < 1):
        print("Error: --repeats and --max-calls must be 1 or greater and --timeout greater than 0.")
        return 1
    try:
        tasks = get_tasks(args.only)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    arms = arm_list(args.noise, args.workflow)

    if args.plan:
        try:
            saved = runner.load_results("race-race")
        except FileNotFoundError:
            saved = None
        pilot = pilot_numbers(args.pilot) if args.pilot else None
        if args.pilot and not pilot:
            print(f"Error: no usable pilot saved as {args.pilot} (it needs runs of both agent and team).")
            return 1
        print("\n".join(plan_lines(arms, tasks, args.repeats, saved, pilot)))
        return 0
    if args.pilot:
        print("Error: --pilot goes with --plan.")
        return 1
    if not args.label:
        print("Error: give this race a name with --label NAME (or print a saved one with --show NAME, or plan one with --plan).")
        return 1
    if not args.model:
        print("Error: name the model with --model, by its exact name (an alias such as the -latest ones can change under you).")
        return 1
    if args.model.endswith("-latest"):
        print(f"Error: {args.model} is an alias that moves. Name the model itself.")
        return 1
    if args.resume and args.force:
        print("Error: --resume carries a race on and --force starts it over: pick one.")
        return 1
    try:
        pipeline.require_index()
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1

    path = runner.results_path("race-" + args.label)
    leftover = path[:-len(".json")] + ".incomplete.json"
    source = leftover if args.resume and os.path.exists(leftover) else path       # progress saved beside a complete race is newer
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    meta = make_meta(args.label, tasks, args.repeats, arms, args.model, started, args.timeout)
    if meta["code"]["dirty"] is None:
        print("WARNING: git could not be read, so this race will not say which commit it ran on.")
    if meta["code"]["dirty"] and not args.allow_dirty:
        print("Error: code under app, evals or scripts has uncommitted changes, so a race could not say which code ran. Commit first "
              "(the order is: the code and prompts, then the prediction, then the race), or run a pilot with --allow-dirty and a pilot- label.")
        return 1
    if args.allow_dirty and not args.label.startswith("pilot-"):
        print("Error: --allow-dirty is for pilots: give the label a pilot- prefix so the result cannot pass for the race.")
        return 1

    if os.path.exists(path) and not (args.resume or args.force):
        print(f"Error: a race is already saved as {display_path(path, BASE_DIR)}. Use another --label, --resume to carry it on, "
              "or --force to start over.")
        return 1
    if args.resume:
        if not os.path.exists(source):
            print(f"Error: there is no saved race to resume at {display_path(path, BASE_DIR)}.")
            return 1
        results = runner.load_results(source)
        same_arms = make_meta(args.label, tasks, args.repeats, results["meta"]["arms"], args.model, started, args.timeout)
        differences = changed_since(results["meta"], same_arms)               # judged on the arms the saved race has
        if differences:
            print("Error: the code or settings changed since this race began, so it cannot be resumed as one race (" + ", ".join(differences)
                  + "). Race again under a new label; the old file stays as evidence.")
            return 1
        saved_meta = results["meta"]
        saved_meta["arms"] = saved_meta["approaches"] = list(dict.fromkeys(list(saved_meta["arms"]) + arms))
        saved_meta["models"] = {arm: args.model for arm in saved_meta["arms"]}
        saved_meta["noise_arm"] = team_report.NOISE if team_report.NOISE in saved_meta["arms"] else None
        saved_meta["config"] = {arm: arm_config(arm, args.timeout) for arm in saved_meta["arms"]}
        saved_meta["caps"] = caps_table(saved_meta["arms"], args.timeout)
        saved_meta["code"] = meta["code"]                                    # the commit it carried on at; the file hashes were just checked equal
        saved_meta["resumed"] = list(saved_meta.get("resumed") or []) + [started]
        saved_meta.update(complete=False, stopped_because=None)
        arms = saved_meta["arms"]
    else:
        results = {"meta": meta, "runs": []}

    plan = build_plan(tasks, args.repeats, arms)
    finished = {(r["repeat"], r["task_id"], r["approach"]) for r in results["runs"]}
    left = sum((repeat, task["id"], arm) not in finished for repeat, task, arm in plan)
    print(f"Racing {', '.join(arms)} on {len(tasks)} task(s) x {args.repeats} repeat(s) = {len(plan)} runs ({left} to do) on {args.model} "
          f"(limits: {settings.agent_max_steps} steps, {settings.agent_max_total_tokens} tokens, {args.timeout:g}s per run; {settings.llm_rpm} calls a minute)")
    print(f"code: {results['meta']['code']['git']}{' (UNCOMMITTED changes: a pilot)' if results['meta']['code']['dirty'] else ''}; "
          f"corpus: {len(results['meta']['corpus'])} files, fingerprint {sha(repr(sorted(results['meta']['corpus'].items())))}\n")
    options = {"model": args.model, "timeout_seconds": args.timeout, "max_calls_per_tool": 0}

    def save(partial):
        partial["meta"]["finished"] = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            runner.save_results(partial, path)
        except OSError as exc:                          # a file another program is holding: say so, the next save writes everything again
            print(f"WARNING: could not save progress ({exc}); the race goes on")

    stopped = run_plan(plan, results, default_tools(), options, save, max_calls=args.max_calls)
    results["meta"].update(complete=stopped is None, stopped_because=stopped,
                           finished=datetime.now().astimezone().isoformat(timespec="seconds"))
    if stopped:
        print(f"\nSTOPPED: {stopped}\nSaved what finished. Carry on with --resume once the cause is gone.")
    try:
        saved_path = runner.save_results(results, path)
    except OSError as exc:
        print(f"Error: could not save the race: {exc}")
        return 1
    if runner.kept_older_run(saved_path):               # a forced race that was cut short must not look like it replaced the old one
        print(f"\nWARNING: '{args.label}' already had a complete saved race, so it was kept, and this partial one was saved beside it as "
              f"{display_path(saved_path, BASE_DIR)}")
    if results["meta"]["complete"] and os.path.exists(leftover):        # a progress save that went beside an older complete file
        os.remove(leftover)
    print()
    print("\n".join(team_report.format_report(results, 0.0, 0.0)))
    print(f"\nsaved: {display_path(saved_path, BASE_DIR)}")
    return 0 if results["meta"]["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
