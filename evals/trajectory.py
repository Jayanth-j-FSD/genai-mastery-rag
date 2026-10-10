"""Grade the PATH an agent took, not only its answer (Week 8, mentor checks #1 and #3).

An agent can reach the right answer by a wrong path, for example by adding 30 days to a date
in its head instead of calling the date tool. It works today by luck and breaks tomorrow on a different date.
So besides "was the answer right" (the OUTCOME, scored by Week 6's rule checks) this module scores the
TRAJECTORY: which tools were used, in what order, with what inputs, and how the run ended.

The failure modes below are plain rules, written here so a reviewer can disagree with any of them. Each
one is something a run's recorded steps can show without a model judging it:

  loop                 repeated an identical call, or never converged (ended on the step limit)
  over-calling         called one tool four or more times, so the run spent its steps re-asking
  wrong-tool           called a tool the task neither needs nor allows (a task may list `allowed_tools`:
                       extras that are legitimate but not required, such as a calculator for a date sum)
  skipped-tool         never called a tool the task needed, so a right answer came from memory or mental arithmetic
  made-up-input        gave add_days a date or a number of days that nobody supplied (not in the question or an
                       earlier result; a number written in words, such as "two weeks", is not recognised)
  unverified-citation  cited a document it never retrieved
  gave-up-quietly      said "I don't know" to an answerable question after at most one search
  no-answer            ended on a limit or an error without answering
  blocked-answer       the defences withheld an answer on a task that had a legitimate one (a false block)

The OUTCOME-VERSUS-TRAJECTORY GAP is the number of runs whose outcome passed while the trajectory showed at
least one failure mode: right answer, wrong path.

Everything works on the records that evals/race.py already saves, so a saved run can be re-graded offline,
for free, as often as the rules change.
"""
import json
import re
from collections import Counter
from types import SimpleNamespace

from app.agent.defense import dates_in
from evals import race

MODES = {
    "loop": "repeated an identical call, or never converged (ended on the step limit)",
    "over-calling": "called one tool four or more times, so the run spent its steps re-asking",
    "wrong-tool": "called a tool the task neither needs nor allows",
    "skipped-tool": "never called a tool the task needed (a right answer came from memory or mental arithmetic)",
    "made-up-input": "gave add_days a date or a number of days that nobody supplied",
    "unverified-citation": "cited a document it never retrieved",
    "gave-up-quietly": "said I don't know to an answerable question after at most one search",
    "no-answer": "ended on a limit or an error without answering",
    "blocked-answer": "the defences withheld the answer to a legitimate question",
}
_ISO_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMBER_RE = re.compile(r"\d+")


def calls_in(record):
    """Every tool call in the run, in order."""
    return [call for step in record.get("steps", []) for call in step.get("tool_calls", [])]


def arguments_of(call):
    """The call's arguments as a dict ({} when they were not valid JSON)."""
    raw = call.get("arguments")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _distinct(names):
    seen = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen


def _is_refusal(answer):
    return (answer or "").lower().replace("\u2019", "'").startswith("i don't know")


_CITATION_RE = re.compile(r"\[source:\s*([^\]]+)\]", re.IGNORECASE)
_SOURCE_PREFIX_RE = re.compile(r"^\s*source:\s*", re.IGNORECASE)


def cited_documents(answer):
    """Every document name the answer cites. One tag may list several, "[source: A.md, B.md]" or
    "[source: A.md; source: B.md]", so each is split and any repeated "source:" prefix is dropped."""
    names = []
    for group in _CITATION_RE.findall(answer or ""):
        for part in re.split(r"[;,]", group):
            name = _SOURCE_PREFIX_RE.sub("", part).strip()
            if name:
                names.append(name)
    return names


def tool_choice_accuracy(task, record):
    """The share of tool calls that were to a tool the task needs. Notes to memory are not counted either way."""
    expected = set(task.get("expected_tools") or []) | set(task.get("allowed_tools") or [])
    names = [call["name"] for call in calls_in(record) if call["name"] != "remember"]
    if not names:
        return 0.0 if expected else 1.0
    return sum(name in expected for name in names) / len(names)


def order_ok(task, record):
    """True when the needed tools that were used were first used in the expected order."""
    expected = _distinct(task.get("expected_tools") or [])
    names = [call["name"] for call in calls_in(record)]
    first_use = [names.index(tool) for tool in expected if tool in names]
    return first_use == sorted(first_use)


def detect_modes(task, record):
    """The failure modes this run shows, as [{"mode": ..., "detail": ...}]. Empty means a clean path."""
    calls = calls_in(record)
    nudged = [call for call in calls if str(call.get("observation", "")).startswith("You already called")]
    names = [call["name"] for call in calls if not call.get("blocked") and call not in nudged]      # calls that really ran
    used = set(names)
    expected = _distinct(task.get("expected_tools") or [])
    answerable = not task.get("should_refuse")
    found = []

    def add(mode, detail):
        found.append({"mode": mode, "detail": detail})

    most_used = max(Counter(names).values(), default=0)
    if nudged or record.get("stop_reason") in ("max_steps", "repeated_call"):
        add("loop", f"{len(nudged)} repeated call(s), stop reason {record.get('stop_reason')!r}")
    if most_used >= 4:
        add("over-calling", f"called {Counter(names).most_common(1)[0][0]} {most_used} times")

    allowed = set(task.get("allowed_tools") or [])
    unneeded = [name for name in _distinct(names) if name not in expected and name not in allowed and name != "remember"]
    if unneeded:
        add("wrong-tool", f"called {unneeded}; the task needs {expected}")

    missing = [tool for tool in expected if tool not in used]
    if missing:
        add("skipped-tool", f"never called {missing}")

    known = dates_in(task.get("question", ""))
    known_numbers = set(_NUMBER_RE.findall(task.get("question", "")))
    for call in calls:
        if call["name"] == "add_days" and not call.get("blocked"):
            arguments = arguments_of(call)
            date = str(arguments.get("date", "")).strip()
            if date not in known:
                add("made-up-input", f"add_days was given the date {date!r}, which the question and earlier results never stated")
            try:
                days = str(abs(int(arguments.get("days"))))
            except (TypeError, ValueError):
                days = None
            if days is not None and days not in known_numbers:
                add("made-up-input", f"add_days was given {days} days, a number the question and earlier results never stated")
        observation = str(call.get("observation", ""))
        known |= dates_in(observation) | set(_ISO_RE.findall(observation))
        known_numbers |= set(_NUMBER_RE.findall(observation))

    answer = record.get("answer") or ""
    if answer and not _is_refusal(answer):
        retrieved = race.retrieved_from_steps(SimpleNamespace(steps=record.get("steps", [])))
        known_sources = {chunk["source"] for chunk in retrieved}
        unseen = [name for name in cited_documents(answer)
                  if not any(source == name or source.rsplit("/", 1)[-1] == name.rsplit("/", 1)[-1] for source in known_sources)]
        if unseen:
            add("unverified-citation", f"cited {unseen}, which the agent never retrieved")

    if answerable and _is_refusal(answer) and names.count("search_policies") <= 1:
        add("gave-up-quietly", f"said I don't know after {names.count('search_policies')} search(es)")
    if record.get("stop_reason") == "output_blocked":
        if answerable:
            add("blocked-answer", "the defences withheld the answer to a legitimate question")
    elif record.get("stop_reason") != "final":
        add("no-answer", f"ended with stop reason {record.get('stop_reason')!r}")
    return found


def grade(task, record):
    """One run, graded on its outcome and on its path."""
    details = detect_modes(task, record)
    modes = [item["mode"] for item in details]
    return {"task_id": task["id"], "outcome_ok": bool(record.get("success")), "modes": modes, "details": details,
            "trajectory_ok": not modes, "tool_choice_accuracy": round(tool_choice_accuracy(task, record), 3),
            "order_ok": order_ok(task, record)}


def grade_all(records, tasks):
    """Grade every record against the task it belongs to. Records of unknown tasks are skipped."""
    by_id = {task["id"]: task for task in tasks}
    return [grade(by_id[record["task_id"]], record) for record in records if record["task_id"] in by_id]


def gap_table(graded):
    """How many runs fall in each cell of outcome (right or wrong) by path (right or wrong)."""
    cells = {"right-answer-right-path": 0, "right-answer-wrong-path": 0,
             "wrong-answer-right-path": 0, "wrong-answer-wrong-path": 0}
    for row in graded:
        cells[("right" if row["outcome_ok"] else "wrong") + "-answer-" + ("right" if row["trajectory_ok"] else "wrong") + "-path"] += 1
    return cells


def mode_counts(graded):
    """{mode: how many runs show it}, most common first. A run counts once per mode however often it did it."""
    counts = Counter(mode for row in graded for mode in set(row["modes"]))
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def rank_modes(graded):
    """Modes ranked by runs affected, then by how many of those runs also got the answer wrong."""
    ranked = []
    for mode, runs in mode_counts(graded).items():
        wrong = sum(1 for row in graded if mode in row["modes"] and not row["outcome_ok"])
        ranked.append({"mode": mode, "runs": runs, "also_wrong_answer": wrong})
    return sorted(ranked, key=lambda item: (-item["runs"], -item["also_wrong_answer"], item["mode"]))


def _stats(values):
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    return {"mean": sum(values) / len(values), "p50": race.percentile(values, 50), "p95": race.percentile(values, 95),
            "p99": race.percentile(values, 99), "max": max(values)}


def cost_summary(records):
    """Tokens, model calls and model seconds per run: mean, median, p95, p99 and max."""
    return {"tokens": _stats([r["prompt_tokens"] + r["completion_tokens"] for r in records]),
            "calls": _stats([r["llm_calls"] for r in records]),
            "api_seconds": _stats([r["api_seconds"] for r in records])}


def tokens_past_call_limit(records, limit=3):
    """Tokens in the steps that made a call beyond `limit` to one tool, and all tokens: a CEILING on what a cap saves.

    It is not a forecast. With a cap the model still has to write an answer, and that step costs tokens too, so
    the real saving is smaller. `remember` is exempt from the cap and calls a defence or a budget refused do not
    count, because neither ran.
    """
    past_limit = total = 0
    for record in records:
        total += record["prompt_tokens"] + record["completion_tokens"]
        counts = {}
        for step in record.get("steps", []):
            beyond = False
            for call in step.get("tool_calls", []):
                if call.get("blocked") or call["name"] == "remember":
                    continue
                counts[call["name"]] = counts.get(call["name"], 0) + 1
                beyond = beyond or counts[call["name"]] > limit
            if beyond:
                past_limit += step["tokens"]["prompt"] + step["tokens"]["completion"]
    return past_limit, total


def summarize(graded, records):
    n = len(graded)
    return {"runs": n, "outcome_ok": sum(row["outcome_ok"] for row in graded),
            "trajectory_ok": sum(row["trajectory_ok"] for row in graded),
            "order_ok": sum(row["order_ok"] for row in graded),
            "tool_choice_accuracy": round(sum(row["tool_choice_accuracy"] for row in graded) / n, 3) if n else 0.0,
            "gap": gap_table(graded), "modes": mode_counts(graded), "ranked": rank_modes(graded),
            "cost": cost_summary(records)}


def format_report(summary, label="agent"):
    n = summary["runs"]
    cost = summary["cost"]
    lines = [f"=== trajectories '{label}': {n} run(s) ===", "",
             f"outcome right (rule checks pass)      {summary['outcome_ok']}/{n}",
             f"trajectory clean (no failure mode)    {summary['trajectory_ok']}/{n}",
             f"needed tools first used in order      {summary['order_ok']}/{n}",
             f"tool-choice accuracy (mean)           {summary['tool_choice_accuracy']:.0%}", "",
             "outcome versus trajectory:"]
    lines += [f"  {name:<26}{count:>4}" for name, count in summary["gap"].items()]
    lines += ["", "failure modes (runs showing each, and how many of those also got the answer wrong):"]
    lines += [f"  {item['mode']:<22}{item['runs']:>4}   {item['also_wrong_answer']} wrong answer(s)   {MODES[item['mode']]}"
              for item in summary["ranked"]] or ["  (none)"]
    lines += ["", f"{'cost per run':<14}{'mean':>9}{'p50':>9}{'p95':>9}{'p99':>9}{'max':>9}"]
    for name, label_text in (("tokens", "tokens"), ("calls", "model calls"), ("api_seconds", "model s")):
        stat = cost[name]
        lines.append(f"{label_text:<14}{stat['mean']:>9.1f}{stat['p50']:>9.1f}{stat['p95']:>9.1f}{stat['p99']:>9.1f}{stat['max']:>9.1f}")
    lines += ["", f"p95 and p99 over {n} run(s) are the highest values or close to them: too few runs for a stable tail."]
    return lines


def format_compare(before, after, label_before="before", label_after="after"):
    """Before and after on the numbers that matter for a fix: outcome, path, modes and cost."""
    def row(name, a, b, fmt="{}"):
        return f"  {name:<36}{fmt.format(a):>12}{fmt.format(b):>12}"
    lines = [f"{'':38}{label_before:>12}{label_after:>12}",
             row("runs", before["runs"], after["runs"]),
             row("outcome right", before["outcome_ok"], after["outcome_ok"]),
             row("trajectory clean", before["trajectory_ok"], after["trajectory_ok"]),
             row("right answer, wrong path (the gap)", before["gap"]["right-answer-wrong-path"], after["gap"]["right-answer-wrong-path"]),
             row("tool-choice accuracy", before["tool_choice_accuracy"], after["tool_choice_accuracy"], "{:.0%}")]
    for mode in sorted(set(before["modes"]) | set(after["modes"])):
        lines.append(row(f"mode: {mode}", before["modes"].get(mode, 0), after["modes"].get(mode, 0)))
    lines.append(row("tokens per run, mean", before["cost"]["tokens"]["mean"], after["cost"]["tokens"]["mean"], "{:.0f}"))
    lines.append(row("tokens per run, p99", before["cost"]["tokens"]["p99"], after["cost"]["tokens"]["p99"], "{:.0f}"))
    return lines
