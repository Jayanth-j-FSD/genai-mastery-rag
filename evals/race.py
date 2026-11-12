"""Race the agent against the fixed workflow on speed, cost and reliability (Week 7, mentor check #3).

"which is better" needs numbers, so this runs every task several times with each approach
and records, for each run:

  reliability  did it finish, and did the rule checks (right document cited, the expected facts present,
               refused when it should) pass? Run each task more than once: a model can get a task right
               twice and wrong once, and one lucky run proves nothing.
  cost         model calls and tokens. A free tier has no dollar cost, but tokens x your provider's
               price is the real one, and calls decide how long a rate limit makes you wait.
  speed        seconds spent INSIDE model calls. Time spent waiting for the free tier's rate limit is left
               out on purpose, because it depends on your quota and would be charged to whichever approach
               makes more calls. `elapsed` (wall clock) is recorded too.

Nothing here decides the winner. The numbers go into docs/week7/findings.md and the decision, which one
you would ship and why, is yours to write.
"""
import copy
import re
import time
import traceback
from collections import Counter
from datetime import datetime
from types import SimpleNamespace

import openai

from app import llm
from app.agent import loop, workflow
from app.agent.tools import default_tools
from app.config import settings
from app.rag import generator
from evals import checks
from evals.agent_tasks import get_tasks

APPROACHES = ("agent", "workflow")

_PASSAGE_RE = re.compile(r"\[\d+\]\s*\[source:\s*([^\]]+?)\s*\]\s*(.*)")
_SOURCE_PREFIX_RE = re.compile(r"^\s*source:\s*", re.IGNORECASE)
MAX_ERRORS_IN_A_ROW = 3          # a provider that fails this many runs in a row is down, not unlucky


def retrieved_from_steps(run):
    """The passages the run actually saw, rebuilt from its search results. Lets the rule checks work on either approach."""
    passages, seen = [], set()
    for step in run.steps:
        for call in step.get("tool_calls", []):
            if call["name"] != "search_policies" or not call.get("ok"):
                continue
            for line in call["observation"].splitlines():
                match = _PASSAGE_RE.match(line.strip())
                if match and (match.group(1), match.group(2)) not in seen:
                    seen.add((match.group(1), match.group(2)))
                    passages.append({"source": match.group(1), "text": match.group(2)})
    return passages


def cited_names(answer):
    """Every document name the answer cites. "[source: A.md; source: B.md]" names both, with the repeated prefix dropped."""
    names = []
    for name in generator._cited_names(answer or ""):
        names.append(name)
        bare = _SOURCE_PREFIX_RE.sub("", name).strip()
        if bare != name:
            names.append(bare)
    return names


def cited_sources(answer, retrieved):
    """Documents the answer cites that were really retrieved (a citation of a document never seen does not count)."""
    known = {chunk["source"] for chunk in retrieved}
    cited = []
    for name in cited_names(answer):
        for source in known:
            if (source == name or source.rsplit("/", 1)[-1] == name.rsplit("/", 1)[-1]) and source not in cited:
                cited.append(source)
    return cited


def to_result(run):
    """The AgentRun as the {answer, grounded, sources, retrieved} dict the rule checks read."""
    retrieved = retrieved_from_steps(run)
    answer = run.answer or ""
    refused = answer.lower().replace("’", "'").startswith("i don't know")
    return {"answer": answer, "grounded": bool(answer) and not refused,
            "sources": cited_sources(answer, retrieved), "retrieved": retrieved}


def percentile(values, p):
    """The p-th percentile by the nearest-rank method (p from 0 to 100). With few values it is just a high one."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * p // 100))          # ceiling without importing math
    return ordered[int(rank) - 1]


def run_one(task, approach, repeat, tools, **options):
    """One run of one task with one approach, scored. Returns a flat, JSON-friendly record."""
    started = time.monotonic()
    if approach == "agent":
        run = loop.run_agent(task["question"], tools, **options)
    elif approach == "workflow":
        run = workflow.run_workflow(task["question"], model=options.get("model"), rpm=options.get("rpm"))
    else:
        raise ValueError(f"unknown approach {approach!r}")
    result = to_result(run)
    rule_checks, passed, warnings = checks.check_case(task, result)
    usage = run.usage or {}
    return {"task_id": task["id"], "approach": approach, "repeat": repeat,
            "success": bool(run.finished and passed), "finished": run.finished, "rules_passed": passed,
            "stop_reason": run.stop_reason, "answer": run.answer, "failed_checks": [c["detail"] for c in rule_checks if not c["passed"]],
            "warnings": warnings, "n_steps": len(run.steps),
            "tool_calls": [call["name"] for step in run.steps for call in step.get("tool_calls", [])],
            "llm_calls": usage.get("calls", 0), "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0), "api_seconds": usage.get("api_seconds", 0.0),
            "wait_seconds": usage.get("wait_seconds", 0.0), "elapsed_seconds": round(time.monotonic() - started, 3),
            "steps": run.steps, "notes": run.notes}


def run_race(tasks=None, approaches=APPROACHES, repeats=3, label="race", say=print, tools=None, **options):
    """Run every task `repeats` times with every approach.

    It stops, keeping every run that finished, when a daily quota runs out, when the provider fails
    MAX_ERRORS_IN_A_ROW runs in a row, or when a run crashes. `meta.complete` is False in each of those cases.
    """
    tasks = tasks if tasks is not None else get_tasks()
    tools = tools if tools is not None else default_tools()
    started = datetime.now().isoformat(timespec="seconds")
    records, stopped, errors_in_a_row = [], None, 0
    plan = [(repeat, task, approach) for repeat in range(1, repeats + 1) for task in tasks for approach in approaches]
    try:
        for repeat, task, approach in plan:
            record = run_one(task, approach, repeat, tools, **options)
            records.append(record)
            flag = "ok  " if record["success"] else "FAIL"
            say(f"[{flag}] {task['id']:<24} {approach:<9} run {repeat}/{repeats}  "
                f"{record['llm_calls']} call(s), {record['prompt_tokens'] + record['completion_tokens']} tokens, "
                f"{record['stop_reason']}")
            errors_in_a_row = errors_in_a_row + 1 if record["stop_reason"] == "error" else 0
            if errors_in_a_row >= MAX_ERRORS_IN_A_ROW:       # one provider error is recorded as a run; a string of them is an outage
                last = (record["steps"][-1].get("content") if record.get("steps") else "") or "no detail recorded"
                stopped = f"{errors_in_a_row} runs in a row ended on a provider error (the last: {last})"
                say(f"\nSTOPPED: {stopped}\nSaved what finished.")
                break
    except (llm.QuotaExhausted, openai.OpenAIError) as exc:
        # A daily quota, or a provider failure that escaped a run: keep every run that finished.
        stopped = str(exc) if isinstance(exc, llm.QuotaExhausted) else f"the provider failed ({type(exc).__name__}): {exc}"
        say(f"\nSTOPPED: {stopped}\nSaved what finished.")
    except Exception as exc:                     # a crash in one run must not lose the runs that finished
        stopped = f"a run failed unexpectedly ({type(exc).__name__}): {exc}"
        say(f"\nSTOPPED: {stopped}\n{traceback.format_exc(limit=-3)}Saved what finished.")
    return {"meta": {"label": label, "started": started, "finished": datetime.now().isoformat(timespec="seconds"),
                     "complete": stopped is None, "stopped_because": stopped, "repeats": repeats,
                     "approaches": list(approaches), "tasks": [t["id"] for t in tasks],
                     "models": {"agent": settings.llm_model, "workflow": settings.llm_model},
                     "limits": {"max_steps": settings.agent_max_steps, "max_total_tokens": settings.agent_max_total_tokens,
                                "timeout_seconds": settings.agent_timeout_seconds},
                     "retrieval_mode": settings.retrieval_mode, "top_k_workflow": workflow.DEFAULT_TOP_K},
            "runs": records}


def rescore(results, tasks=None):
    """The same runs scored against the CURRENT task definitions, from their stored answers and steps. No model calls.

    A race is scored with the rule checks as they stood when it ran. When a check or a task is tightened later,
    this recomputes success for every stored run so the comparison can be re-read under the stricter rules. The
    original is never modified: a copy comes back, marked, and each changed run is listed in meta.
    """
    by_id = {task["id"]: task for task in (tasks if tasks is not None else get_tasks())}
    scored = copy.deepcopy(results)
    changed, skipped = [], []
    for record in scored["runs"]:
        task = by_id.get(record["task_id"])
        if task is None:                         # the task was renamed or removed: keep the old verdict, and say so
            skipped.append({"task_id": record["task_id"], "approach": record["approach"], "repeat": record["repeat"]})
            continue
        result = to_result(SimpleNamespace(steps=record["steps"], answer=record["answer"]))
        rule_checks, passed, warnings = checks.check_case(task, result)
        success = bool(record["finished"] and passed)
        if success != record["success"]:
            changed.append({"task_id": record["task_id"], "approach": record["approach"], "repeat": record["repeat"],
                            "was": record["success"], "now": success})
        record.update(rules_passed=passed, success=success, warnings=warnings,
                      failed_checks=[c["detail"] for c in rule_checks if not c["passed"]])
    scored["meta"] = dict(scored["meta"], rescored=True, rescored_changes=changed, rescored_skipped=skipped)
    return scored


def summarize(results):
    """Per-approach totals and a per-task success grid."""
    per_approach = {}
    for approach in results["meta"]["approaches"]:
        rows = [r for r in results["runs"] if r["approach"] == approach]
        if not rows:
            continue
        tokens = [r["prompt_tokens"] + r["completion_tokens"] for r in rows]
        seconds = [r["api_seconds"] for r in rows]
        per_approach[approach] = {
            "runs": len(rows), "success": sum(r["success"] for r in rows), "finished": sum(r["finished"] for r in rows),
            "calls_mean": sum(r["llm_calls"] for r in rows) / len(rows), "calls_max": max(r["llm_calls"] for r in rows),
            "tokens_mean": sum(tokens) / len(rows), "tokens_max": max(tokens), "tokens_p95": percentile(tokens, 95),
            "seconds_mean": sum(seconds) / len(rows), "seconds_max": max(seconds), "seconds_p95": percentile(seconds, 95),
            "stop_reasons": dict(Counter(r["stop_reason"] for r in rows)),
        }
    grid = {}
    for row in results["runs"]:
        cell = grid.setdefault(row["task_id"], {}).setdefault(row["approach"], [0, 0])
        cell[0] += row["success"]
        cell[1] += 1
    costs = {}
    for row in results["runs"]:
        bucket = costs.setdefault(row["task_id"], {}).setdefault(row["approach"], {"calls": [], "tokens": []})
        bucket["calls"].append(row["llm_calls"])
        bucket["tokens"].append(row["prompt_tokens"] + row["completion_tokens"])
    costs = {task: {approach: {"calls": sum(v["calls"]) / len(v["calls"]), "tokens": sum(v["tokens"]) / len(v["tokens"])}
                    for approach, v in per.items()} for task, per in costs.items()}
    return {"approaches": per_approach, "grid": grid, "costs": costs}


def format_summary(results):
    summary = summarize(results)
    meta = results["meta"]
    lines = [f"=== race '{meta['label']}': {meta['repeats']} run(s) of {len(meta['tasks'])} task(s), model {meta['models']['agent']} ===", ""]
    lines.append(f"{'approach':<10}{'runs':>5}{'success':>9}{'finished':>10}{'calls avg':>11}{'tokens avg':>12}"
                 f"{'model s avg':>13}{'model s p95':>13}")
    for approach, row in summary["approaches"].items():
        lines.append(f"{approach:<10}{row['runs']:>5}{row['success']:>6}/{row['runs']:<3}{row['finished']:>7}/{row['runs']:<3}"
                     f"{row['calls_mean']:>11.1f}{row['tokens_mean']:>12.0f}{row['seconds_mean']:>13.1f}{row['seconds_p95']:>13.1f}")
    lines += ["", "stop reasons: " + "; ".join(f"{a}: {r['stop_reasons']}" for a, r in summary["approaches"].items()), ""]
    lines.append(f"{'task':<26}" + "".join(f"{a + ' ok':>13}{'calls':>7}{'tokens':>8}" for a in meta["approaches"]))
    for task_id, cells in summary["grid"].items():
        row = f"{task_id:<26}"
        for approach in meta["approaches"]:
            ok, runs = cells.get(approach, [0, 0])
            cost = summary["costs"].get(task_id, {}).get(approach, {"calls": 0, "tokens": 0})
            row += f"{ok:>10}/{runs:<2}{cost['calls']:>7.1f}{cost['tokens']:>8.0f}"
        lines.append(row)
    lines += ["", "success = finished AND passed the rule checks. 'model s' is time inside model calls: waiting for the "
              "free tier's rate limit is excluded. p95 over so few runs is close to the maximum.",
              "The decision about which to ship, and why, is yours: write it in docs/week7/findings.md."]
    return lines
