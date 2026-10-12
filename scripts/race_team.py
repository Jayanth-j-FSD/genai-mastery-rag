"""Week 10, mentor checks #1 to #3: race the team against the single agent on the SAME tasks, and print the four numbers.

The same nine tasks, the same model, the same rule checks and the same limits on tokens and time, run once
as the single agent and once as the team (a manager and two specialists), several times each. The report gives quality,
speed, tokens and cost for both, so a verdict about which design to use, and why, can rest on numbers even if the team
lost. The verdict itself is yours to write; this prints the evidence.

The runs are interleaved: repeat by repeat, task by task, one run of every arm before the next task, with the arm order
rotating. If a free-tier quota ends the race part-way, every arm has almost the same runs, and the provider's mood at any
hour is shared by all of them. `--noise` adds a second, identical single-agent arm (`agent-2`) that calibrates the method.

Before a race counts it is frozen: the code, the prompts and the prediction (docs/week10/prediction.md) are committed (a race refuses
an uncommitted tree, an uncommitted prediction and a git it cannot read; only a pilot, whose label starts with `pilot-`, may run on
one; the files a race writes under evals/results and evals/cache are not code). Every result records the git commit, a hash of every
.py file under app and evals and of the two race scripts, the corpus and the settings it ran with, and a race cannot be resumed
after any of them changed. A resume keeps the stamp the race began on and adds the commit it carried on at to meta.code_history.

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
(carry on) or --force (start over). A forced race moves what it would overwrite to race-<label>.replaced-<time>.json and says so;
an older complete race stays in place while the new one is cut short, and moves aside only when the new one replaces it.
Name the model: never the alias.
"""
import argparse
import contextlib
import hashlib
import inspect
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openai                                                # noqa: E402
from app import llm                                          # noqa: E402
from app.agent import loop, team, tools as agent_tools, workflow     # noqa: E402
from app.agent.tools import default_tools                    # noqa: E402
from app.config import BASE_DIR, settings                    # noqa: E402
from app.console import display_path, make_output_safe       # noqa: E402
from app.rag import loader, pipeline, store                  # noqa: E402
from evals import race, runner, team_report                  # noqa: E402
from evals.agent_tasks import get_tasks                      # noqa: E402

BASE = {"agent": "agent", "team": "team", "agent-2": "agent", "workflow": "workflow"}      # what each arm label runs
STAMPED_FILES = ("app/agent/team.py", "app/agent/loop.py", "app/llm.py", "evals/checks.py", "evals/agent_tasks.py", "evals/race.py",
                 "evals/team_prediction.py")                                              # hashed into every result, each under its own name
CODE_ROOTS = ("app", "evals")                                  # every .py file under these decides what a run does, so every one is hashed
CODE_SCRIPTS = ("scripts/race_team.py", "scripts/pilot_team.py")       # and these two scripts, which build the runs and the plan
GENERATED = ("evals/results", "evals/cache")                   # what a race writes: output, never code, so it never counts as uncommitted code
PREDICTION_DOC = "docs/week10/prediction.md"                   # committed before the race, so that git shows the order
SETTING_NAMES = ("llm_max_retries", "llm_timeout_seconds", "dense_search", "hybrid_candidates", "rrf_k", "bm25_k1", "bm25_b", "embed_provider")
PLAIN = str.maketrans({"\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})   # typographic marks a model writes, as plain ASCII
DEFAULT_TIMEOUT = 300.0        # seconds a run may take: wider than the 120 s default because the free tier's rate-limit pauses count, for BOTH arms
CODE_KEYS = tuple(os.path.basename(path) for path in STAMPED_FILES)
LOCK_STALE_SECONDS = 600       # a race saves after every run and a run is capped at DEFAULT_TIMEOUT, so a label quiet this long was left behind by a crash
GIT_PROBLEM = {"text": ""}     # why the latest git command failed, so a refusal can say what went wrong and not only that git was unreadable


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
    """The output of one git command in the project, or None when git is missing or the command fails (GIT_PROBLEM keeps why)."""
    try:
        out = subprocess.run(["git", *args], cwd=BASE_DIR, capture_output=True, encoding="utf-8", errors="replace", timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        GIT_PROBLEM["text"] = f"{type(exc).__name__}: {exc}"
        return None
    if out.returncode != 0:
        reason = (out.stderr or "").strip().splitlines()
        GIT_PROBLEM["text"] = reason[0] if reason else f"git {args[0]} exited with {out.returncode}"
        return None
    return out.stdout.strip()


def uncommitted_code():
    """The paths under app, evals and scripts that git says are changed or new, or None when git cannot be read. A race's own result and
    cache files are what it writes, not the code it ran, so they are left out: they would otherwise forbid every resume."""
    status = git("status", "--porcelain", "--", "app", "evals", "scripts", *[f":(exclude){path}" for path in GENERATED])
    return None if status is None else [line.strip().split(None, 1)[-1] for line in status.splitlines() if line.strip()]


def code_files():
    """{path: hash} of every .py file under app and evals (a race's own results and cache aside) and of the two race scripts: everything
    that decides what a run does, the memory and the search tool included, not only the files a reader would think of first."""
    found = set(CODE_SCRIPTS) | set(STAMPED_FILES)
    for root in CODE_ROOTS:
        for folder, dirs, names in os.walk(os.path.join(BASE_DIR, root)):
            here = os.path.relpath(folder, BASE_DIR).replace("\\", "/")
            dirs[:] = [d for d in dirs if f"{here}/{d}" not in GENERATED and d != "__pycache__"]
            found.update(f"{here}/{name}" for name in names if name.endswith(".py"))
    return {path: file_sha(path) for path in sorted(found)}


def code_stamp(files=None):
    """Which code ran: the git commit, whether code under app, evals or scripts had uncommitted changes (and which), a hash of each
    stamped file under its own name, and a fingerprint of every code file (the per-file hashes are `code_files`)."""
    files = code_files() if files is None else files
    paths = uncommitted_code()
    stamp = {"git": git("rev-parse", "--short", "HEAD") or "unknown", "dirty": None if paths is None else bool(paths)}
    if stamp["git"] == "unknown" or paths is None:
        stamp["git_problem"] = scrub_text(GIT_PROBLEM["text"] or "no reason given")        # why git could not be read: a refusal and a pilot's record both say it
    if paths:
        stamp["dirty_paths"] = ", ".join(paths)
    stamp.update({os.path.basename(path): files.get(path) for path in STAMPED_FILES})
    stamp["tree"] = sha(repr(sorted(files.items())))
    return stamp


def prediction_doc_state():
    """(blob, problem) for the prediction document: the git hash of the file as committed, or None and a sentence saying what is wrong
    (not committed, changed since, or git unreadable). The prediction is committed before the race so that git shows the order."""
    blob = git("rev-parse", f"HEAD:{PREDICTION_DOC}")
    if blob is None:
        return None, f"{PREDICTION_DOC} is not committed (git said: {GIT_PROBLEM['text']})"
    changed = git("status", "--porcelain", "--", PREDICTION_DOC)
    if changed is None:
        return None, f"git could not check {PREDICTION_DOC} ({GIT_PROBLEM['text']})"
    if changed:
        return None, f"{PREDICTION_DOC} has uncommitted changes"
    return blob, None


def settings_snapshot():
    """The settings, beyond the limits meta already holds, that change what a run does or sees, and the size of the index it searched."""
    snapshot = {name: getattr(settings, name) for name in SETTING_NAMES}
    snapshot["chunk_count"] = store.count_chunks()
    return snapshot


def corpus_fingerprint():
    """Every document the index is built from (the loader's rules: sub-folders too, .txt .md .pdf), with a hash of its text. Line endings
    are normalised for text, as for code, so the same commit gives the same fingerprint on any checkout."""
    files = {}
    for folder, _dirs, names in os.walk(settings.corpus_dir):
        for name in sorted(names):
            if os.path.splitext(name)[1].lower() not in loader.SUPPORTED:
                continue
            path = os.path.join(folder, name)
            with open(path, "rb") as handle:
                data = handle.read()
            if not name.lower().endswith(".pdf"):
                data = data.replace(b"\r\n", b"\n")
            files[os.path.relpath(path, settings.corpus_dir).replace("\\", "/")] = hashlib.sha256(data).hexdigest()[:12]
    return dict(sorted(files.items()))


def scrub_text(text, limit=300):
    """Text that may reach a tracked file: the API key, the project's path and the home folder (a personal name is in it) replaced, in
    the forms an error message shows them (plain, forward slashes, doubled backslashes as repr() writes them, any case), and cut short."""
    text = str(text)
    key = settings.openai_api_key
    if key and len(key) >= 8:
        text = text.replace(key, "<key>")
    base = str(BASE_DIR)                                              # a Path in the app, a str in tests: Path.replace would RENAME a file
    for place, name in ((base, "<project>"), (os.path.expanduser("~"), "<home>")):
        if len(place) < 4:                                            # "~" when the home folder is unknown: nothing to replace, and it would eat a tilde
            continue
        for form in {place, place.replace("\\", "/"), place.replace("\\", "\\\\")}:
            text = re.sub(re.escape(form), name, text, flags=re.IGNORECASE)
    return text[:limit]


def make_encodable(value):
    """Replace, in place, any lone surrogate in a record's text (half an emoji, from a model) with '?': it cannot be written to a UTF-8
    file, and one such character must not lose the run. Returns the value."""
    if isinstance(value, dict):
        for key, item in value.items():
            value[key] = make_encodable(item)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = make_encodable(item)
    elif isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    return value


def scrub_record(record):
    """Provider error text in a run's steps is cut and scrubbed before it can be saved in a public repo, and the record made writable."""
    for step in record.get("steps") or []:
        if step.get("kind") == "error":
            step["content"] = scrub_text(step.get("content", ""))
    return make_encodable(record)


def plain(lines):
    """The report's lines with the long dashes and curly quotes a model wrote turned into plain ASCII: the project does not use them."""
    return [line.translate(PLAIN) for line in lines]


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
    files = code_files()                                  # read once, so the stamp's fingerprint and the saved per-file hashes cannot disagree
    return {"label": label, "started": started, "complete": False, "stopped_because": None, "repeats": repeats,
            "approaches": list(arms), "arms": list(arms), "tasks": [task["id"] for task in tasks], "interleaved": True,
            "models": {arm: model for arm in arms}, "noise_arm": team_report.NOISE if team_report.NOISE in arms else None,
            "limits": {"max_steps": settings.agent_max_steps, "max_total_tokens": settings.agent_max_total_tokens, "timeout_seconds": timeout,
                       "agent_max_calls_per_tool": 0},
            "llm_rpm": settings.llm_rpm, "retrieval_mode": settings.retrieval_mode,
            "search": {"top_k default": inspect.signature(agent_tools.search_policies).parameters["top_k"].default,
                       "passage chars": agent_tools._MAX_PASSAGE_CHARS, "retrieval mode": settings.retrieval_mode},
            "config": {arm: arm_config(arm, timeout) for arm in arms}, "caps": caps_table(arms, timeout),
            "code": code_stamp(files), "code_files": files, "code_history": [], "settings": settings_snapshot(),
            "prediction_doc": prediction_doc_state()[0], "corpus": corpus_fingerprint(), "resumed": [], "not_interleaved_arms": []}


def provider_trouble(record):
    """A run that ended on provider trouble (an error, a spent quota or an empty reply), either the manager's own or a specialist's.
    It is the report's own test, so what stops a race, what a resume runs again and what the report leaves out can never disagree."""
    return team_report.provider_trouble(record)


def usage_cross_check(record, scope):
    """None when the per-call records add up to what the run reported, else a sentence saying how they differ. A scope that saw no
    call is compared too: a run that made none and reports none is equal, and one that reports calls nobody recorded is the instrument failing."""
    counted = scope.totals(deep=True)
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


def requests_from(call_log, llm_calls, failed=False):
    """Requests one run sent to the provider: every attempt of every call, the retried and the failed ones included, which is what a
    free daily quota counts. Never fewer than the calls that succeeded, and at least one for a run that ended on a provider error."""
    sent = sum(call.get("attempts", 1) for call in call_log)
    return max(sent, llm_calls, 1 if failed else 0)


def run_plan(plan, results, tools, options, save, say=print, run_one=None, max_calls=None):
    """Run what the plan lists and the results do not have yet, saving after every run. Stops, keeping what finished, when a
    quota runs out, when MAX_ERRORS_IN_A_ROW runs in a row (of any arms, or of one arm) hit provider trouble (an error, a spent quota or an
    empty reply), when a run crashes,
    when a run's usage does not add up or a hand-off failed on a bug, or when --max-calls REQUESTS have been sent. Returns the reason, or None."""
    run_one = run_one or race.run_one
    done = {(run["repeat"], run["task_id"], run["approach"]) for run in results["runs"]}
    repeats, errors_in_a_row, calls_used = results["meta"]["repeats"], 0, 0
    arm_streaks = {}                                               # per arm: the arms alternate, so one arm failing alone must not be reset by the other
    for repeat, task, arm in plan:
        if (repeat, task["id"], arm) in done:
            continue
        if max_calls is not None and calls_used >= max_calls:
            return f"--max-calls {max_calls} reached ({calls_used} requests used in this session)"
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
        requests = requests_from(team_report.calls_of(record), record["llm_calls"], provider_trouble(record))     # retries count against the day's quota
        calls_used += requests
        say(f"[{'ok  ' if record['success'] else 'FAIL'}] {task['id']:<24} {arm:<9} repeat {repeat}/{repeats}  "
            f"{record['llm_calls']} call(s){f' ({requests} requests)' if requests != record['llm_calls'] else ''}, "
            f"{record['prompt_tokens'] + record['completion_tokens']} tokens, {record['stop_reason']}")
        crew = record.get("team") or {}
        if record.get("usage_warning") or crew.get("warnings"):
            return scrub_text(f"a run's per-agent usage did not add up to the process counters: {record.get('usage_warning') or crew['warnings'][0]}")
        if crew.get("errors"):
            return f"a hand-off failed on a bug in the team code ({crew['errors'][0]['type']} in the {crew['errors'][0]['agent']}); fix it and race again"
        trouble = provider_trouble(record)
        errors_in_a_row = errors_in_a_row + 1 if trouble else 0
        arm_streaks[arm] = arm_streaks.get(arm, 0) + 1 if trouble else 0
        if errors_in_a_row >= race.MAX_ERRORS_IN_A_ROW or arm_streaks[arm] >= race.MAX_ERRORS_IN_A_ROW:        # one provider error is a run; a string of them is an outage
            steps = record.get("steps") or [{}]
            last = steps[-1].get("content") or f"stop reason {record['stop_reason']}, no detail recorded"
            if errors_in_a_row >= race.MAX_ERRORS_IN_A_ROW:
                return scrub_text(f"{errors_in_a_row} runs in a row ended on a provider error (the last: {last})")
            return scrub_text(f"{arm_streaks[arm]} runs in a row ended on a provider error in the {arm} arm, while the other arms were fine (the last: {last})")
    return None


def resume_hint(args, results):
    """Lines for a finished race that has runs on provider trouble: how many, what running them again costs, and the command that does."""
    bad = [run for run in results["runs"] if team_report.provider_trouble(run)]
    if not bad:
        return []
    good = [requests_from(team_report.calls_of(run), run["llm_calls"]) for run in results["runs"] if not team_report.provider_trouble(run)]
    cost = f" (about {round(len(bad) * sum(good) / len(good))} requests)" if good else ""
    command = ["python scripts/race_team.py", "--label", args.label, "--model", args.model]
    if args.only:
        command += ["--only", *args.only]
    if args.repeats != 3:
        command += ["--repeats", str(args.repeats)]
    if args.timeout != DEFAULT_TIMEOUT:
        command += ["--timeout", f"{args.timeout:g}"]
    return [f"\n{len(bad)} run{' ended' if len(bad) == 1 else 's ended'} on provider trouble (an error, a spent quota or an empty reply). "
            "The report leaves them out; they say nothing about the design.",
            f"Run {'it' if len(bad) == 1 else 'them'} again{cost}, once the provider is working, with: {' '.join(command)} --resume"]


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
        rows["team"], line = pilot_team_line(pilot, agent_per_run, lean)
        lines.append(line)
    elif lean:
        lines.append(f"team: between {lean:.1f} and {high:.1f} model calls a run (an ESTIMATE from a model of the hand-offs on that race's tool mix, not a measurement)")
        rows["team"] = (lean + high) / 2
    total = sum(rows.get(arm, 0) * runs for arm in arms)
    lines.append(f"about {total:.0f} model calls in all" + (f", {total / settings.llm_rpm:.0f} minutes at {settings.llm_rpm} calls a minute" if settings.llm_rpm else "")
                 + ". A lite model's free key allowed about 500 requests a model a day when measured, and retries count against it: "
                   "give the race a model nothing else is using that day, and set --max-calls (it counts requests, retries included) below the cap.")
    return lines


def pilot_team_line(pilot, agent_per_run, lean):
    """(team calls a run, the plan line) from a pilot. Its questions are easier than the race tasks, so its team-to-agent ratio is applied to
    what the single agent makes on the race tasks, and the result is never lower than the lean estimate of the hand-off model."""
    where = f"on {pilot['n']} pilot question(s) that are not race tasks"
    if not (pilot.get("agent") and agent_per_run):
        team_calls = max(pilot["team"], lean or 0)
        return team_calls, (f"team: {team_calls:.1f} model calls a run, measured {where} (the single agent made {pilot['agent']:.1f} on the same); "
                            "not scaled, because there is no saved race (or no single-agent calls in the pilot) to scale by")
    ratio = pilot["team"] / pilot["agent"]
    scaled = ratio * agent_per_run
    team_calls = max(scaled, lean or 0)
    return team_calls, (f"team: {team_calls:.1f} model calls a run, SCALED from a pilot: {where} the team made {pilot['team']:.1f} calls where the single "
                        f"agent made {pilot['agent']:.1f} (x{ratio:.2f}), and the single agent makes {agent_per_run:.1f} on the race tasks"
                        + (f"; raised to the lean estimate of {lean:.1f}, the least the model of the hand-offs allows" if team_calls > scaled else ""))


def mean_calls(saved, approach):
    rows = [run["llm_calls"] for run in (saved or {"runs": []})["runs"] if run["approach"] == approach]
    return sum(rows) / len(rows) if rows else 0.0


def pilot_numbers(path_or_label):
    """Calls per run for each arm of a saved pilot (scripts/pilot_team.py), or None when there is none."""
    try:
        saved = runner.load_results(path_or_label)
    except FileNotFoundError:
        return None
    team_runs = [run for run in saved["runs"] if run.get("arm") == "team"]           # a race's rows say "approach", not "arm": not a pilot
    agent_runs = [run for run in saved["runs"] if run.get("arm") == "agent"]
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
    lines = plain(team_report.format_report(saved, price_in, price_out, source))
    command = f"python scripts/race_team.py --show {args.show}" + (f" --price-in {args.price_in} --price-out {args.price_out} "
                                                                  f"--price-source \"{source}\"" if source else "") + (" --rescore" if args.rescore else "")
    if args.rescore:
        rescored = race.rescore(saved)
        changed = rescored["meta"]["rescored_changes"]
        lines = ["AS RACED (the rule checks as they were when the race ran):", ""] + lines
        lines += ["", "=" * 78, "RE-SCORED with today's rule checks (same runs, same answers, no model calls):", ""]
        lines += plain(team_report.format_report(rescored, price_in, price_out, source))
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
    if saved_meta.get("code_files") is not None and meta.get("code_files") is not None:          # a race saved before every file was hashed has only the stamped ones
        differences += [path for path in changed_files(saved_meta["code_files"], meta["code_files"]) if os.path.basename(path) not in differences]
    for arm, setting in (saved_meta.get("config") or {}).items():
        if meta["config"].get(arm) != setting:
            differences.append(f"config of {arm}")
    for name, value in (saved_meta.get("settings") or {}).items():                              # only what the saved race recorded can be compared
        if (meta.get("settings") or {}).get(name) != value:
            differences.append(f"setting {name}")
    if saved_meta.get("prediction_doc") and saved_meta["prediction_doc"] != meta.get("prediction_doc"):
        differences.append("prediction_doc")                      # the prediction was edited after the race began: it is no longer the one registered first
    return differences


def changed_files(saved, now):
    """The paths whose hash differs between two {path: hash} dicts, a file that appeared or went away included."""
    return sorted(path for path in set(saved) | set(now) if saved.get(path) != now.get(path))


def accept_changes(differences, named, saved_meta, meta):
    """What a person may accept: a code file that changed since the race began. Returns (the differences that remain, {path: {"was", "now"}},
    a problem sentence or None). Settings, tasks, the corpus and the prediction cannot be accepted: they are what makes it one race."""
    saved_files, files = saved_meta.get("code_files"), meta.get("code_files")
    if saved_files is None or files is None:
        return differences, {}, ("this race was saved before every code file was hashed, so --accept-changed cannot name what changed. "
                                 "Race again under a new label; the old file stays as evidence.")
    changed = changed_files(saved_files, files)
    wanted = []
    for name in named:
        name = name.replace("\\", "/")
        wanted.append(name[2:] if name.startswith("./") else name)
    unknown = [name for name in wanted if name not in changed]
    if unknown:
        return differences, {}, (f"--accept-changed names {', '.join(unknown)}, which is not among the code files that changed since the race began "
                                 f"({', '.join(changed) or 'none changed'}).")
    dropped = set(wanted) | {os.path.basename(name) for name in wanted if name in STAMPED_FILES}        # a stamped file is listed under its bare name
    return [difference for difference in differences if difference not in dropped], \
        {name: {"was": saved_files.get(name), "now": files.get(name)} for name in wanted}, None


def read_meta(path):
    """The meta of a saved race, or None when the file is missing, unreadable or not a race."""
    try:
        return runner.load_results(path)["meta"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def when(meta):
    """When a saved race last wrote its file, as a datetime, or None when it did not say."""
    try:
        return datetime.fromisoformat(meta.get("finished") or meta["started"])
    except (KeyError, TypeError, ValueError):
        return None


def newer_progress(path, leftover):
    """The file a --resume carries on from: the leftover when it was written after the saved race (a resume, or a forced race,
    that was cut short while a complete race sat at the label), else the saved race itself."""
    if not os.path.exists(leftover):
        return path
    saved, beside = read_meta(path), read_meta(leftover)
    if saved is None or beside is None:
        return path
    try:
        return leftover if when(beside) >= when(saved) else path
    except TypeError:                                    # a time that was not recorded, or has no zone: a leftover only ever sits beside a complete race
        return leftover if saved.get("complete") else path


def keep_aside(path, say=print):
    """Move a saved race to a name of its own, because a saved race is evidence and a write that would replace it must not destroy it."""
    stem = path[:-len(".json")]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target, number = f"{stem}.replaced-{stamp}.json", 1
    while os.path.exists(target):                        # two in the same second must not overwrite each other
        number += 1
        target = f"{stem}.replaced-{stamp}-{number}.json"
    runner._replace_with_retries(path, target)           # the same retried rename the saves use: another program may hold the file for a moment
    say(f"Kept the saved race: {display_path(path, BASE_DIR)} was moved to {display_path(target, BASE_DIR)}.")
    return target


def keep_before_a_forced_race(path, leftover):
    """--force starts over, but a saved race is evidence. The first save would overwrite a leftover or an unfinished race, so those
    move aside now. A COMPLETE race stays where it is, because runner.save_results keeps it while the new race is cut short; it
    moves aside only when the new race completes and would replace it (keep_other_race)."""
    for old in (leftover, path):
        if not os.path.exists(old):
            continue
        meta = read_meta(old)
        if old == path and meta is not None and meta.get("complete"):
            continue
        keep_aside(old)


def keep_other_race(path, meta):
    """Before a complete race is written over the file at `path`: if that file is another race (another start time), move it aside."""
    if not os.path.exists(path):
        return
    other = read_meta(path)
    if other is None or other.get("started") != meta.get("started"):
        keep_aside(path)


class RaceBusy(Exception):
    """Another process is racing under the label."""


def lock_path(path):
    """The lock file of a label: beside its result, named after it, so two labels never share one."""
    return path[:-len(".json")] + ".lock"


def newest_touch(*paths):
    """When the newest of these files was last written, in seconds since the epoch (0 when none exists)."""
    stamps = []
    for path in paths:
        try:
            stamps.append(os.path.getmtime(path))
        except OSError:
            pass
    return max(stamps, default=0.0)


@contextlib.contextmanager
def race_lock(path, break_lock=False, say=print):
    """Hold a label's lock for as long as the race runs, so a second race (a resume started by hand while the first still runs, or the
    same command twice) cannot read half a file and write over its runs. A lock is stale when neither it nor the saved race has been
    written for LOCK_STALE_SECONDS: a race saves after every run, so a crash left it. --break-lock takes it whatever its age."""
    lock = lock_path(path)
    beside = (path, path[:-len(".json")] + ".incomplete.json")
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    for _attempt in range(2):
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)       # exclusive: only one process can create the file
            break
        except FileExistsError:
            quiet = time.time() - newest_touch(lock, *beside)
            if not break_lock and quiet < LOCK_STALE_SECONDS:
                raise RaceBusy(f"another race may already be running under this label: {os.path.basename(lock)} was written {quiet:.0f}s ago (a lock "
                               f"counts as left behind after {LOCK_STALE_SECONDS}s of quiet). If no race is running, take the lock with --break-lock.")
            say(f"{'Breaking the lock' if break_lock else 'Taking over a stale lock'} {os.path.basename(lock)} (last written {quiet:.0f}s ago).")
            try:
                os.remove(lock)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise RaceBusy(f"could not remove {os.path.basename(lock)} ({exc})") from exc
    else:
        raise RaceBusy(f"could not take {os.path.basename(lock)}: another race took it first.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(f"pid {os.getpid()}\n")
        yield
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass                                      # the race is over either way: a lock that cannot be removed goes stale on its own


def why_set_aside(record):
    """Why a run that ended on provider trouble is run again, in the words of the report's own test (team_report.provider_trouble)."""
    if record["stop_reason"] in team_report.TROUBLE_STOPS:
        return f"the run ended on {record['stop_reason']}"
    for handoff in (record.get("team") or {}).get("handoffs", []):
        if handoff.get("stop_reason") in team_report.TROUBLE_STOPS:
            return f"a hand-off ended on {handoff['stop_reason']}"
    return "the run recorded a usage warning or a team error"


def resume(args, tasks, arms, meta, started, path, source):
    """Load a saved race and make it ready to carry on: (results, arms, None), or (None, None, exit code) when it cannot, or need not, be resumed."""
    if not os.path.exists(source):
        print(f"Error: there is no saved race to resume at {display_path(path, BASE_DIR)}.")
        return None, None, 1
    try:
        results = runner.load_results(source)
    except ValueError as exc:                           # a file cut off by a crash, or edited by hand
        print(f"Error: {display_path(source, BASE_DIR)} cannot be read as a saved race ({exc}).")
        return None, None, 1
    saved_meta = results.get("meta") or {}
    if "arms" not in saved_meta or any("approach" not in run for run in results.get("runs", [])):
        print(f"Error: {display_path(source, BASE_DIR)} is not a Week 10 race (it records no arms), so it cannot be resumed.")
        return None, None, 1
    same_arms = make_meta(args.label, tasks, args.repeats, saved_meta["arms"], args.model, started, args.timeout)
    differences = changed_since(saved_meta, same_arms)                        # judged on the arms the saved race has
    accepted = {}
    if differences and args.accept_changed:
        differences, accepted, problem = accept_changes(differences, args.accept_changed, saved_meta, same_arms)
        if problem:
            print(f"Error: {problem}")
            return None, None, 1
    if differences:
        now_changed = changed_files(saved_meta["code_files"], same_arms["code_files"]) if saved_meta.get("code_files") is not None else []
        how = (f" If a changed code file cannot affect what a run does (a comment, a message), name it with --accept-changed PATH "
               f"({', '.join(now_changed)}): the file's history then records that you accepted it. Settings, tasks and the prediction cannot be accepted."
               if now_changed else "")
        print("Error: the code or settings changed since this race began, so it cannot be resumed as one race (" + ", ".join(differences)
              + "). Race again under a new label; the old file stays as evidence." + how)
        return None, None, 1
    if accepted:
        print(f"Accepted changes to {', '.join(accepted)}: recorded in the race file's history.")
    merged = list(dict.fromkeys(list(saved_meta["arms"]) + arms))
    trouble = [team_report.provider_trouble(run) for run in results["runs"]]  # the report's own test: such a run measured the provider, not the design
    have = {(run["repeat"], run["task_id"], run["approach"]) for run, bad in zip(results["runs"], trouble) if not bad}
    if saved_meta.get("complete") and source == path and all((repeat, task["id"], arm) in have for repeat, task, arm in build_plan(tasks, args.repeats, merged)):
        print(f"Nothing to resume: the race saved as {display_path(path, BASE_DIR)} is complete and has every run. Nothing was changed.")
        return None, None, 0                            # a resume that runs nothing must not rewrite the file or its provenance
    aside = [run for run, bad in zip(results["runs"], trouble) if bad]
    if aside:                                           # kept as they were, so nothing is lost, but they run again instead of counting as failures
        saved_meta["set_aside_runs"] = list(saved_meta.get("set_aside_runs") or []) + [dict(run, set_aside_because=why_set_aside(run)) for run in aside]
        results["runs"] = [run for run, bad in zip(results["runs"], trouble) if not bad]
        print(f"Set aside {len(aside)} run(s) that ended on provider trouble: they run again, and stay in the file under set_aside_runs "
              f"({', '.join(f'{run['task_id']} {run['approach']} #{run['repeat']}' for run in aside[:5])}{', ...' if len(aside) > 5 else ''}).")
    added = [arm for arm in merged if arm not in saved_meta["arms"]]
    saved_meta["arms"] = saved_meta["approaches"] = merged
    saved_meta["models"] = {arm: args.model for arm in merged}
    saved_meta["noise_arm"] = team_report.NOISE if team_report.NOISE in merged else None
    saved_meta["config"] = {arm: arm_config(arm, args.timeout) for arm in merged}
    saved_meta["caps"] = caps_table(merged, args.timeout)
    saved_meta["code_history"] = list(saved_meta.get("code_history") or []) + [{"at": started, "code": meta["code"]}]    # meta.code stays the stamp the race BEGAN on
    session = {"at": started, "arms_added": added, "rpm": settings.llm_rpm, "model": args.model, "code": meta["code"]}
    if accepted:
        session["accepted_changes"] = accepted                  # what the person said could not matter, with the hash before and after
    saved_meta["resumed"] = [entry if isinstance(entry, dict) else {"at": entry} for entry in saved_meta.get("resumed") or []] + [session]
    saved_meta["not_interleaved_arms"] = list(dict.fromkeys(list(saved_meta.get("not_interleaved_arms") or []) + added))   # they ran after the others
    saved_meta.update(complete=False, stopped_because=None)
    return results, merged, None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Race the team against the single agent on the same tasks.")
    parser.add_argument("--label", default=None, help="name of this race (saved as evals/results/race-<label>.json)")
    parser.add_argument("--repeats", type=int, default=3, help="runs per task and arm (default 3)")
    parser.add_argument("--only", nargs="+", metavar="ID", help="race only these task ids")
    parser.add_argument("--noise", action="store_true", help="add a second identical single-agent arm (agent-2): a calibration of the method")
    parser.add_argument("--workflow", action="store_true", help="add the fixed workflow as a reference arm (one model call a run)")
    parser.add_argument("--model", default=None, help="chat model for every arm, by its exact name (required to race: an alias can move)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help=f"seconds a run may take, for every arm (default {DEFAULT_TIMEOUT:g})")
    parser.add_argument("--max-calls", type=int, default=None, help="stop after this many REQUESTS to the provider in this session, retried and failed ones included (keep it below the day's quota)")
    parser.add_argument("--plan", action="store_true", help="print what the race would take in requests and minutes, then stop (no model calls)")
    parser.add_argument("--pilot", metavar="LABEL", default=None, help="with --plan: a saved pilot whose team-to-agent calls ratio scales the estimate")
    parser.add_argument("--allow-dirty", action="store_true", help="race on an uncommitted tree: only for a label that starts with pilot-")
    parser.add_argument("--resume", action="store_true", help="carry on a saved race that stopped early, under the same label")
    parser.add_argument("--force", action="store_true", help="start over under a label that is already saved")
    parser.add_argument("--accept-changed", action="append", default=[], metavar="PATH",
                        help="with --resume: carry on although this code file changed since the race began (repeat for several); for a change that cannot affect a run, such as a comment")
    parser.add_argument("--break-lock", action="store_true", help="take the label's lock although it looks fresh: only when no other race is running under it")
    parser.add_argument("--show", metavar="LABEL", help="print the report of a saved race (no model calls) instead of racing")
    parser.add_argument("--price-in", type=float, default=None, help="with --show: dollars per million INPUT tokens, a price you state")
    parser.add_argument("--price-out", type=float, default=None, help="with --show: dollars per million OUTPUT tokens, a price you state")
    parser.add_argument("--price-source", default=None, help="with --show: where you read those prices and when (required with them)")
    parser.add_argument("--rescore", action="store_true", help="with --show: score the saved answers with the current rule checks and list what changed")
    parser.add_argument("--save", action="store_true", help="with --show: also write docs/week10/race-results.md")
    args = parser.parse_args(argv)
    make_output_safe()
    try:
        sys.stdout.reconfigure(line_buffering=True)        # so a race run in the background shows each run as it ends, not at the end
    except (AttributeError, ValueError):
        pass

    for flag, value in (("--price-in", args.price_in), ("--price-out", args.price_out)):
        if value is not None and not 0 <= value < math.inf:                 # nan fails every comparison, so it is caught here too
            print(f"Error: {flag} must be 0 or more and finite, got {value}.")
            return 1
    if args.show:
        return show(args)
    for flag, used in (("--price-in", args.price_in is not None), ("--price-out", args.price_out is not None), ("--price-source", bool(args.price_source)),
                       ("--rescore", args.rescore), ("--save", args.save)):
        if used:                                        # silently ignored, they would look like they had worked
            print(f"Error: {flag} works on a saved race, so it needs --show LABEL.")
            return 1
    if args.repeats < 1 or not 0 < args.timeout < math.inf or (args.max_calls is not None and args.max_calls < 1):
        print("Error: --repeats and --max-calls must be 1 or greater and --timeout greater than 0 and finite.")
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
    if args.label == "race":
        print("Error: the label race is reserved: race-race.json is the saved Week 7 race that --plan reads. Pick another label.")
        return 1
    if args.resume and args.force:
        print("Error: --resume carries a race on and --force starts it over: pick one.")
        return 1
    if args.accept_changed and not args.resume:
        print("Error: --accept-changed goes with --resume: a new race starts on the code as it is.")
        return 1
    try:
        pipeline.require_index()
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1

    path = runner.results_path("race-" + args.label)
    try:
        with race_lock(path, args.break_lock):
            return run_race(args, tasks, arms, path)
    except RaceBusy as exc:
        print(f"Error: {exc}")
        return 1


def run_race(args, tasks, arms, path):
    """Everything from the checks on the saved files to the report, while this process holds the label's lock."""
    leftover = path[:-len(".json")] + ".incomplete.json"
    source = newer_progress(path, leftover) if args.resume else path               # progress saved beside a complete race may be newer
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    meta = make_meta(args.label, tasks, args.repeats, arms, args.model, started, args.timeout)
    code, is_pilot = meta["code"], args.label.startswith("pilot-")
    if code["dirty"] is None or code["git"] == "unknown":
        if not is_pilot:                                # a race that cannot say which commit it ran on is not frozen: refuse it, as for dirty code
            print(f"Error: git could not be read ({code.get('git_problem', 'no reason given')}), so a race could not say which commit it ran on. "
                  "Make git work in this folder, or run a pilot (a label that starts with pilot-).")
            return 1
        print("WARNING: git could not be read, so this race will not say which commit it ran on.")
    if code["dirty"] and not args.allow_dirty:
        print(f"Error: code under app, evals or scripts has uncommitted changes ({code.get('dirty_paths', 'see git status')}), so a race could not "
              "say which code ran. Commit first (the order is: the code and prompts, then the prediction, then the race), or run a pilot with "
              "--allow-dirty and a pilot- label.")
        return 1
    if args.allow_dirty and not is_pilot:
        print("Error: --allow-dirty is for pilots: give the label a pilot- prefix so the result cannot pass for the race.")
        return 1
    if not is_pilot and meta["prediction_doc"] is None:
        print(f"Error: {prediction_doc_state()[1]}. Commit the prediction before the race, so that git shows it came first.")
        return 1

    if os.path.exists(path) and not (args.resume or args.force):
        print(f"Error: a race is already saved as {display_path(path, BASE_DIR)}. Use another --label, --resume to carry it on, "
              "or --force to start over.")
        return 1
    if args.resume:
        results, arms, exit_code = resume(args, tasks, arms, meta, started, path, source)
        if results is None:
            return exit_code
    else:
        if args.force:
            try:
                keep_before_a_forced_race(path, leftover)
            except OSError as exc:
                print(f"Error: could not move the saved race aside ({exc}), so the forced race was not started and nothing was changed.")
                return 1
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

    try:
        stopped = run_plan(plan, results, default_tools(), options, save, max_calls=args.max_calls)
    except KeyboardInterrupt:                           # the runs that finished are already saved; the one in flight is lost and runs again
        stopped = "interrupted by the user (Ctrl-C)"
    results["meta"].update(complete=stopped is None, stopped_because=stopped,
                           finished=datetime.now().astimezone().isoformat(timespec="seconds"))
    if stopped:
        print(f"\nSTOPPED: {stopped}\nSaved what finished. Carry on with --resume once the cause is gone.")
    try:
        if results["meta"]["complete"]:
            keep_other_race(path, results["meta"])      # a forced race that finished replaces the old one: the old one is kept aside
        saved_path = runner.save_results(results, path)
    except OSError as exc:
        print(f"Error: could not save the race: {exc}")
        return 1
    if runner.kept_older_run(saved_path):               # a forced race that was cut short must not look like it replaced the old one
        print(f"\nWARNING: '{args.label}' already had a complete saved race, so it was kept, and this partial one was saved beside it as "
              f"{display_path(saved_path, BASE_DIR)}")
    if results["meta"]["complete"] and os.path.exists(leftover):        # a progress save that went beside an older complete file
        beside = read_meta(leftover)
        if beside is not None and beside.get("started") == results["meta"].get("started"):      # only this race's own progress: another's is evidence
            os.remove(leftover)
    if results["meta"]["complete"]:
        for arm in arms:
            mine = [run for run in results["runs"] if run["approach"] == arm]
            if mine and all(team_report.provider_trouble(run) for run in mine):
                print(f"\nWARNING: every run of the {arm} arm ended on provider trouble, so this race measured the provider and not the design. "
                      "Do not quote it: find the cause and race again under a new label.")
        for line in resume_hint(args, results):
            print(line)
    print()
    print("\n".join(plain(team_report.format_report(results, 0.0, 0.0))))
    print(f"\nsaved: {display_path(saved_path, BASE_DIR)}")
    return 0 if results["meta"]["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
