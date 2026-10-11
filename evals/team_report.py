"""The numbers for the team-versus-single-agent race (Week 10): quality, speed, tokens and cost, per arm and per agent.

Week 7 raced an agent against a fixed recipe. This week races a TEAM (a manager that hands work to two
specialists) against the single agent, on the same tasks, with the same model. The mentor asks for four numbers about
both, and an honest verdict even if the team lost:

  quality  how many runs finished AND passed the rule checks. With a few dozen runs a gap of one or two runs is not
           resolved, so the report gives a 95% interval beside every rate and, for the same task and repeat under two
           arms, the discordant pairs with the exact McNemar p. The repeats of a task are near-copies, so both of those
           treat them as independent and are optimistic: a by-task line (the arms' pass counts compared task by task, with
           the exact sign test over tasks) sits beside the pair line. A second identical single-agent arm (`agent-2`), when
           the race has one, is a calibration of that method: its comparison with `agent` should show no difference.
  speed    seconds inside model calls (what the work costs when no rate limit slows it) AND wall-clock seconds, which here
           mostly measure queueing behind the free tier's rate limit. Calls per run is the other speed number.
  tokens   prompt and completion separately. A prompt is mostly the conversation so far, re-sent on every step. The report
           splits the prompt tokens it can measure into the OPENING of each conversation (system prompt, tool list and
           question: a team opens one conversation per hand-off) and everything LATER (an upper bound on re-sent text,
           because it also holds new tool results).
  cost     the free tier bills nothing and this project has no price table, so cost is reported without inventing a
           price: in RELATIVE units (an input token is 1 unit, an output token is r units, for r = 1, 2, 4, 8 and 20), as
           the one claim that holds for any one input price and one output price (the cost ratio lies between the
           input-token ratio and the output-token ratio; a cheaper price for cached input is a third price it does not
           cover), and as requests, which is what a free tier is spent in. Dollars appear only when you state prices and
           where you got them (app/pricing.py), labelled as an assumption.

Everything marked "derived" is worked out from recorded numbers, not measured: the extra prompt tokens a hand-off that
carried the whole conversation would have cost (a floor and a ceiling), the tokens the manager re-reads from the
specialists' answers (an upper bound), and the elapsed seconds saved if hand-offs had overlapped.

Nothing here decides the winner. The numbers go into docs/week10/findings.md; the verdict is yours to write.
"""
import json
import math
import re

from app import pricing
from evals import trajectory
from evals.agent_tasks import PATH_PROBES, TASKS, get_tasks

AGENT, TEAM, NOISE, WORKFLOW = "agent", "team", "agent-2", "workflow"
AGENTS = ("manager", "researcher", "calculator")
PRICE_RATIOS = (1, 2, 4, 8, 20)    # output tokens cost this many input tokens: 1 is the plain token count, the rest a grid to read against the prices you state
UNIT_WIDTH = 14                    # the width of every column of the cost tables, heading and rows alike, so they line up
NEAR_CEILING = 0.90                # a single-agent success rate from here up leaves little room above it
DAILY_REQUESTS = 500               # what a free-tier key allowed per model per day when measured (docs/week8)
LIMIT_STOPS = ("max_steps", "timeout", "token_budget", "repeated_call", "budget")       # a run ended on a limit, not on an answer
TROUBLE_STOPS = ("error", "quota_exhausted", "empty_reply")                               # a run ended on the provider: a failed call, a spent quota, or a reply with no text and no tool request
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


# ---------------------------------------------------------------------------- small statistics

def mean(values):
    return sum(values) / len(values) if values else 0.0


def median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if not ordered:
        return 0.0
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def wilson(successes, runs, z=1.96):
    """The 95% Wilson interval for a success rate, as (low, high). It stays inside 0 to 1 and behaves with few runs."""
    if runs <= 0:
        return 0.0, 0.0
    rate = successes / runs
    spread = 1 + z * z / runs
    centre = rate + z * z / (2 * runs)
    margin = z * math.sqrt(rate * (1 - rate) / runs + z * z / (4 * runs * runs))
    return max(0.0, (centre - margin) / spread), min(1.0, (centre + margin) / spread)


def mcnemar_exact(only_first, only_second):
    """The exact two-sided p of McNemar's test: given the discordant pairs (one arm passed, the other did not), how likely
    is a split at least this lopsided if the arms were equally likely to win each. 1.0 when there are no such pairs."""
    pairs = only_first + only_second
    if pairs == 0:
        return 1.0
    tail = sum(math.comb(pairs, k) for k in range(min(only_first, only_second) + 1))
    return min(1.0, 2 * tail / 2 ** pairs)


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _stated(price):
    """A price the caller did not state is 0.0, 'not stated': the report never reads the PRICE_* settings, so a saved report
    cannot change with whatever is in somebody's .env."""
    return 0.0 if price is None else price


# ---------------------------------------------------------------------------- where the prompt tokens went

def conversations(steps):
    """The model calls of one run grouped into conversations, each a list of (prompt, completion) tokens in order.

    A single agent has one conversation. A team has the manager's and one per hand-off. A step with no tokens at all is
    skipped: usually no model call is behind it (an error before any reply), but a provider reply with no choices IS billed
    and counted although the loop records its step with 0 tokens, so a run's step tokens can fall short of its total
    (`tokens_in_no_step` measures the gap).
    """
    groups = {}
    for step in steps:
        tokens = step.get("tokens") or {}
        if not (tokens.get("prompt") or tokens.get("completion")):
            continue
        groups.setdefault((step.get("agent"), step.get("handoff")), []).append((tokens.get("prompt", 0), tokens.get("completion", 0)))
    return groups


def tokens_in_no_step(record):
    """Tokens a run was billed beyond what its steps record (a provider reply with no choices leaves a step with 0 tokens), derived as
    the run's prompt plus completion tokens minus the sum over its steps. 0 for a run with no step record at all: there is nothing to compare."""
    steps = record.get("steps") or []
    if not steps:
        return 0
    seen = sum((step.get("tokens") or {}).get("prompt", 0) + (step.get("tokens") or {}).get("completion", 0) for step in steps)
    return max(0, record["prompt_tokens"] + record["completion_tokens"] - seen)


def prompt_breakdown(steps):
    """Split a run's prompt tokens into opening + later, both measured from each step's own count.

    opening  the first call of every conversation: the system prompt, the tool list and the question.
    later    every other call's prompt: the conversation so far sent again PLUS whatever the step added, so an upper bound
             on re-sent text. `shrank` counts the calls whose prompt was smaller than the call before it (Week 7's memory
             shortens old results), where "later" cannot be all re-sent text.
    """
    opening = later = shrank = 0
    for calls in conversations(steps).values():
        for index, (prompt, _completion) in enumerate(calls):
            if index == 0:
                opening += prompt
            else:
                later += prompt
                shrank += prompt < calls[index - 1][0]
    return {"opening": opening, "later": later, "shrank": shrank}


def _manager_prompts(record):
    """The manager's prompt tokens at each of its steps, keyed by the step's own number (local_n)."""
    return {step.get("local_n"): (step.get("tokens") or {}).get("prompt", 0)
            for step in record.get("steps", []) if step.get("agent") == "manager"}


def forwarded_context_extra(record):
    """Prompt tokens a team run WOULD have added had every hand-off carried the manager's whole conversation so far (derived).

    The CEILING of an estimate: for each hand-off, the manager's prompt at the step that asked for it, counted once per model
    call the specialist made (each of those calls would have re-sent it). That prompt includes the manager's own tool list,
    which forwarding the conversation would not carry, so the true figure is lower; `forwarded_context_floor` is the other end.
    The measured team hands over only the sub-question.
    """
    team = record.get("team")
    if not team:
        return 0
    manager_prompt = _manager_prompts(record)
    return sum(manager_prompt.get(handoff.get("after_manager_step"), 0) * handoff.get("calls", 0)
               for handoff in team["handoffs"] if handoff.get("state") != "refused")


def forwarded_context_floor(record):
    """The FLOOR of the same estimate (derived): only the conversation history the manager had picked up when it asked, that
    is its prompt at the asking step minus its first prompt (system prompt, tool list and question), once per specialist call.
    0 when the manager's first step is not in the record, because then there is nothing to subtract."""
    team = record.get("team")
    manager_prompt = _manager_prompts(record) if team else {}
    if 1 not in manager_prompt:
        return 0
    return sum(max(0, manager_prompt.get(handoff.get("after_manager_step"), 0) - manager_prompt[1]) * handoff.get("calls", 0)
               for handoff in team["handoffs"] if handoff.get("state") != "refused")


def handoff_answers_reread(record):
    """Prompt tokens the manager spends re-reading the specialists' answers (derived): each answer's completion tokens,
    times the manager calls made after the step that asked for it, since the answer sits in the manager's conversation.
    An upper bound: Memory shortens tool results older than the two newest, which this does not subtract."""
    team = record.get("team")
    if not team:
        return 0
    manager_steps = [step for step in record.get("steps", []) if step.get("agent") == "manager"]
    total = 0
    for step in record.get("steps", []):
        if step.get("agent") in ("researcher", "calculator") and step.get("kind") == "final":
            asked = next((h["after_manager_step"] for h in team["handoffs"] if h["handoff"] == step.get("handoff")), None)
            if asked is not None:
                total += (step.get("tokens") or {}).get("completion", 0) * sum(1 for m in manager_steps if m.get("local_n", 0) > asked)
    return total


def overlap_saving(record):
    """Elapsed seconds a team run would have saved had the hand-offs the manager asked for in ONE step run side by side:
    their summed model seconds minus the longest. Derived: the loop runs them one after the other, and the free tier's
    request limit would serialise them anyway, so this says what a parallel team could gain in elapsed time (the summed
    model seconds would not change), not what this one did."""
    team = record.get("team")
    if not team:
        return 0.0
    by_step = {}
    for handoff in team["handoffs"]:
        if handoff.get("state") != "refused":
            by_step.setdefault(handoff.get("after_manager_step"), []).append(handoff.get("api_seconds", 0.0))
    return sum(sum(times) - max(times) for times in by_step.values() if len(times) > 1)


def duplicate_searches(record):
    """Searches in a run that repeat an earlier query of the same run, across hand-offs too (the loop's own guard works inside
    one agent's run only: it refuses an exact repeat of a call and stops the run after two in a row, and it never sees a query
    another agent already made)."""
    seen, repeats = set(), 0
    for step in record.get("steps", []):
        for call in step.get("tool_calls", []):
            if call.get("name") != "search_policies":
                continue
            raw = call.get("arguments")
            try:
                query = json.loads(raw).get("query", "") if isinstance(raw, str) else (raw or {}).get("query", "")
            except (ValueError, AttributeError):
                query = str(raw)
            key = " ".join(str(query).lower().split())
            repeats += key in seen
            seen.add(key)
    return repeats


# ---------------------------------------------------------------------------- what kind of run it was

def ended_on_limit(record):
    """True when the run ITSELF ended on a limit (its own stop reason): a specialist's cap that the manager worked around is not this."""
    return record["stop_reason"] in LIMIT_STOPS


def hit_limit(record):
    """True when the run, or any hand-off in it, ended on a limit instead of an answer."""
    handoffs = (record.get("team") or {}).get("handoffs", [])
    return ended_on_limit(record) or any(h.get("stop_reason") in LIMIT_STOPS for h in handoffs)


def asked_side_by_side(record):
    """True when the manager asked for two or more hand-offs in ONE of its steps (a refused one was never run, so it does not count).
    Read from the hand-offs themselves, not from the seconds they took: two hand-offs that each took 0.0 seconds still overlapped."""
    asked = {}
    for handoff in (record.get("team") or {}).get("handoffs", []):
        step = handoff.get("after_manager_step")
        if handoff.get("state") != "refused" and step is not None:
            asked[step] = asked.get(step, 0) + 1
    return any(count > 1 for count in asked.values())


def provider_trouble(record):
    """True when the run ended on a provider problem (an error, a spent quota or an empty reply), or a specialist did, or the team
    recorded a warning or an internal error. Such a run says nothing about the design, so the clean set leaves its unit out."""
    team = record.get("team") or {}
    return (record["stop_reason"] in TROUBLE_STOPS or any(h.get("stop_reason") in TROUBLE_STOPS for h in team.get("handoffs", []))
            or bool(team.get("warnings")) or bool(team.get("errors")) or bool(record.get("usage_warning")))


def answer_features(record):
    """What the answer and the path look like, apart from whether the rule checks passed."""
    answer = record.get("answer") or ""
    steps = record.get("steps", [])
    searched = any(call.get("name") == "search_policies" for step in steps for call in step.get("tool_calls", []))
    handed = bool((record.get("team") or {}).get("handoffs"))
    refused = answer.lower().replace("\u2019", "'").startswith("i don't know")
    return {"chars": len(answer), "documents": len(trajectory.cited_documents(answer)), "refused": refused,       # documents, each once: one tag may name several
            "refused_without_searching": refused and not searched, "answered_without_hand_off": bool(answer) and not refused and not handed}


# ---------------------------------------------------------------------------- per-arm numbers

def arm_names(results):
    """The arms in the order the race listed them (a result saved by an older script may only list approaches)."""
    meta = results["meta"]
    return list(meta.get("arms") or meta.get("approaches") or sorted({run["approach"] for run in results["runs"]}))


def calls_of(record):
    """The per-call records of a run, whichever arm made it (the team keeps its own, the others have the script's)."""
    return (record.get("team") or {}).get("call_log") or record.get("call_log") or []


def requests_of(record):
    """Requests a run spent against the provider (derived): every attempt in its per-call records when they were kept (a retried call and
    a failed call each cost requests), and never fewer than its successful calls, so a short or missing log cannot lower the count."""
    return max(record["llm_calls"], sum(call.get("attempts", 1) for call in calls_of(record)))


def arm_stats(results, arm, input_price=None, output_price=None):
    """Everything the report says about one arm, as plain numbers. A price left as None is 'not stated', never a setting."""
    input_price, output_price = _stated(input_price), _stated(output_price)
    rows = [run for run in results["runs"] if run["approach"] == arm]
    runs = len(rows)
    wins = sum(bool(run["success"]) for run in rows)
    prompt, completion = [run["prompt_tokens"] for run in rows], [run["completion_tokens"] for run in rows]
    total = [p + c for p, c in zip(prompt, completion)]
    calls = [run["llm_calls"] for run in rows]
    requests = [requests_of(run) for run in rows]
    model_seconds, elapsed = [run["api_seconds"] for run in rows], [run["elapsed_seconds"] for run in rows]
    costs = [pricing.cost_of(run["prompt_tokens"], run["completion_tokens"], input_price, output_price) for run in rows]
    priced = bool(rows) and all(cost is not None for cost in costs)
    pieces = [prompt_breakdown(run.get("steps") or []) for run in rows]
    features = [answer_features(run) for run in rows]
    low, high = wilson(wins, runs)
    units = {r: [p + r * c for p, c in zip(prompt, completion)] for r in PRICE_RATIOS}
    return {
        "runs": runs, "success": wins, "finished": sum(bool(run["finished"]) for run in rows),
        "success_rate": wins / runs if runs else 0.0, "interval": [low, high],
        "calls_mean": mean(calls), "calls_max": max(calls, default=0), "calls_over_8": sum(c > 8 for c in calls),
        "calls_over_12": sum(c > 12 for c in calls), "requests_mean": mean(requests), "runs_per_day": ratio(DAILY_REQUESTS, mean(requests)),
        "prompt_mean": mean(prompt), "completion_mean": mean(completion), "tokens_mean": mean(total),
        "tokens_median": median(total), "tokens_max": max(total, default=0),
        "tokens_per_success": sum(total) / wins if wins else None,
        "model_seconds_mean": mean(model_seconds), "model_seconds_median": median(model_seconds), "model_seconds_max": max(model_seconds, default=0.0),
        "elapsed_mean": mean(elapsed), "elapsed_median": median(elapsed), "elapsed_max": max(elapsed, default=0.0),
        "wait_mean": mean([run["wait_seconds"] for run in rows]),
        "opening_mean": mean([piece["opening"] for piece in pieces]), "later_mean": mean([piece["later"] for piece in pieces]),
        "shrank_calls": sum(piece["shrank"] for piece in pieces),
        "units_mean": {r: mean(values) for r, values in units.items()},
        "units_per_success": {r: (sum(values) / wins if wins else None) for r, values in units.items()},
        "cost_mean": mean(costs) if priced else None,
        "cost_per_success": (sum(costs) / wins) if priced and wins else None,
        "stop_reasons": _counts(run["stop_reason"] for run in rows),
        "forwarded_extra_mean": mean([forwarded_context_extra(run) for run in rows]),
        "forwarded_floor_mean": mean([forwarded_context_floor(run) for run in rows]),
        "reread_mean": mean([handoff_answers_reread(run) for run in rows]),
        "overlap_saving_mean": mean([overlap_saving(run) for run in rows]),
        "duplicate_searches_mean": mean([duplicate_searches(run) for run in rows]),
        "answer_chars_mean": mean([f["chars"] for f in features]), "documents_mean": mean([f["documents"] for f in features]),
        "refused": sum(f["refused"] for f in features), "refused_without_searching": sum(f["refused_without_searching"] for f in features),
        "answered_without_hand_off": sum(f["answered_without_hand_off"] for f in features) if arm == TEAM else None,
        "limit_stops": sum(hit_limit(run) for run in rows), "provider_trouble": sum(provider_trouble(run) for run in rows),
        "own_limit_stops": sum(ended_on_limit(run) for run in rows), "side_by_side_runs": sum(asked_side_by_side(run) for run in rows),
        "no_step_tokens": sum(tokens_in_no_step(run) for run in rows), "no_step_runs": sum(tokens_in_no_step(run) > 0 for run in rows),
    }


def _counts(items):
    counts = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts


def instrument_stats(results, arm):
    """What the per-call records say about how the arm was measured: served models, retries, errors and token gaps."""
    rows = [run for run in results["runs"] if run["approach"] == arm]
    calls = [call for run in rows for call in calls_of(run)]
    reporting_total = [call for call in calls if call.get("total_tokens") is not None]
    return {"runs": len(rows), "calls": len(calls), "recorded": sum(bool(calls_of(run)) for run in rows),
            "served": sorted({call["served"] for call in calls if call.get("served")} | {run["served_model"] for run in rows if run.get("served_model")}),
            "retried": sum(call.get("attempts", 1) > 1 for call in calls),
            "retry_wait": round(sum(call.get("wait_seconds", 0.0) for call in calls if call.get("attempts", 1) > 1), 1),
            "errors": sum(call.get("status") == "error" for call in calls),
            "total_reported": len(reporting_total),
            "unexplained_tokens": sum(call["total_tokens"] - call["prompt_tokens"] - call["completion_tokens"] for call in reporting_total),
            "unexplained_abs": sum(abs(call["total_tokens"] - call["prompt_tokens"] - call["completion_tokens"]) for call in reporting_total),
            "cached_tokens": sum(call.get("cached_tokens") or 0 for call in calls),
            "reasoning_tokens": sum(call.get("reasoning_tokens") or 0 for call in calls),
            "warnings": sum(len((run.get("team") or {}).get("warnings", [])) + bool(run.get("usage_warning")) for run in rows),
            "internal_errors": sum(len((run.get("team") or {}).get("errors", [])) for run in rows)}


def per_agent_stats(results, arm=TEAM):
    """What each agent of the team spent, summed over its runs, and how the hand-offs ended."""
    rows = [run for run in results["runs"] if run["approach"] == arm and run.get("team")]
    totals = {agent: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "api_seconds": 0.0, "handoffs": 0} for agent in AGENTS}
    states, stops = {}, {}
    for run in rows:
        for agent, row in run["team"]["per_agent"].items():
            for key in totals[agent]:
                totals[agent][key] += row.get(key, 0)
        for handoff in run["team"]["handoffs"]:
            states[(handoff["agent"], handoff["state"])] = states.get((handoff["agent"], handoff["state"]), 0) + 1
            key = (handoff["agent"], handoff["state"], handoff.get("stop_reason") or "none")
            stops[key] = stops.get(key, 0) + 1
    grand = sum(row["prompt_tokens"] + row["completion_tokens"] for row in totals.values())
    for agent, row in totals.items():
        row["tokens"] = row["prompt_tokens"] + row["completion_tokens"]
        row["token_share"] = row["tokens"] / grand if grand else 0.0
        row["calls_per_handoff"] = ratio(row["calls"], row["handoffs"]) if agent != "manager" else None
    return {"runs": len(rows), "agents": totals, "handoff_states": {f"{agent}:{state}": n for (agent, state), n in sorted(states.items())},
            "handoff_stops": {f"{agent}:{state}:{reason}": n for (agent, state, reason), n in sorted(stops.items())}}


def team_by_task(results, arm=TEAM):
    """For every task: the team's mean hand-offs and model calls per run, by agent."""
    cells = {}
    for run in results["runs"]:
        if run["approach"] == arm and run.get("team"):
            cell = cells.setdefault(run["task_id"], {"runs": 0, "handoffs": {a: 0 for a in AGENTS}, "calls": {a: 0 for a in AGENTS}})
            cell["runs"] += 1
            for agent, row in run["team"]["per_agent"].items():
                cell["handoffs"][agent] += row.get("handoffs", 0)
                cell["calls"][agent] += row.get("calls", 0)
    return {task: {"runs": cell["runs"], "handoffs": {a: n / cell["runs"] for a, n in cell["handoffs"].items()},
                   "calls": {a: n / cell["runs"] for a, n in cell["calls"].items()}} for task, cell in cells.items()}


def paired(results, first=AGENT, second=TEAM):
    """The same task and repeat under two arms: how often both passed, only one did, or neither did, with the exact McNemar p.
    `unpaired` lists the (task, repeat) cells that only one of the two arms has, so a partial race is never hidden."""
    outcome = {(run["task_id"], run["repeat"], run["approach"]): bool(run["success"]) for run in results["runs"]}
    cells = sorted({(task, repeat) for task, repeat, arm in outcome if arm in (first, second)})
    counts = {"both": 0, "only_" + first: 0, "only_" + second: 0, "neither": 0, "pairs": 0, "unpaired": []}
    for task, repeat in cells:
        if (task, repeat, first) not in outcome or (task, repeat, second) not in outcome:
            counts["unpaired"].append(f"{task} repeat {repeat}")
            continue
        a, b = outcome[(task, repeat, first)], outcome[(task, repeat, second)]
        counts["pairs"] += 1
        counts["both" if a and b else "only_" + first if a else "only_" + second if b else "neither"] += 1
    counts["p"] = mcnemar_exact(counts["only_" + first], counts["only_" + second])
    return counts


def paired_by_task(results, first=AGENT, second=TEAM):
    """The pair comparison with the TASK as the unit, because the repeats of a task are near-copies, not independent trials.

    For every task with at least one pair (the same repeat under both arms): which arm passed more of those repeats, or neither.
    The exact two-sided sign test is over the tasks where the two differ, the test `mcnemar_exact` runs with tasks for pairs."""
    outcome = {(run["task_id"], run["repeat"], run["approach"]): bool(run["success"]) for run in results["runs"]}
    passes = {}
    for (task, repeat, arm), won in outcome.items():
        if arm == first and (task, repeat, second) in outcome:
            cell = passes.setdefault(task, [0, 0])
            cell[0] += won
            cell[1] += outcome[(task, repeat, second)]
    more_first, more_second = sum(a > b for a, b in passes.values()), sum(b > a for a, b in passes.values())
    return {"tasks": len(passes), "more_" + first: more_first, "more_" + second: more_second,
            "same": len(passes) - more_first - more_second, "p": mcnemar_exact(more_first, more_second)}


def task_shape(task_id):
    """How a task's parts depend on each other, from what the task itself says a good run needs.

    dependent    a lookup, then a calculation on its result (the calculator cannot start before the researcher is done)
    independent  two lookups, or facts from two documents, that need not wait for each other
    single       one lookup
    This is the brief's test for when a team can help: parts that are truly independent, or that need clearly different instructions.
    """
    task = {task["id"]: task for task in TASKS + PATH_PROBES}.get(task_id)
    if task is None:
        return "unknown"
    tools = task.get("expected_tools", [])
    if any(name in ("calculate", "add_days") for name in tools):
        return "dependent"
    if tools.count("search_policies") >= 2 or len(task.get("expected_sources", [])) >= 2:
        return "independent"
    return "single"


def per_task(results, arms):
    """For every task: its dependency shape, and per arm the successes out of runs, mean calls and mean tokens."""
    table = {}
    for run in results["runs"]:
        if run["approach"] in arms:
            cell = table.setdefault(run["task_id"], {}).setdefault(run["approach"], {"ok": 0, "runs": 0, "calls": [], "tokens": []})
            cell["ok"] += bool(run["success"])
            cell["runs"] += 1
            cell["calls"].append(run["llm_calls"])
            cell["tokens"].append(run["prompt_tokens"] + run["completion_tokens"])
    return {task: {"shape": task_shape(task),
                   **{arm: {"ok": cell["ok"], "runs": cell["runs"], "calls": mean(cell["calls"]), "tokens": mean(cell["tokens"])}
                      for arm, cell in cells.items()}} for task, cells in table.items()}


def failed_runs(results, arms, limit=200):
    """Every run that did not succeed, with why: the arm, the stop reason, the checks it failed and the start of its answer."""
    return [{"task": run["task_id"], "arm": run["approach"], "repeat": run["repeat"], "stop_reason": run["stop_reason"],
             "failed_checks": list(run.get("failed_checks") or []), "answer": (run.get("answer") or "")[:limit]}
            for run in sorted(results["runs"], key=lambda r: (r["approach"], r["task_id"], r["repeat"]))
            if run["approach"] in arms and not run["success"]]


def path_view(record):
    """A run as Week 8's path grader should read it. For a team the manager's own tool calls (the hand-offs) are dropped, because
    they are not tool use in the sense the grader means, and the specialists' calls stay in time order. Other runs are unchanged."""
    if not record.get("team"):
        return record
    steps = [dict(step, tool_calls=[] if step.get("agent") == "manager" else step.get("tool_calls", [])) for step in record.get("steps", [])]
    return dict(record, steps=steps)


def path_stats(results, arms, tasks=None):
    """Per arm: the right-answer-wrong-path table and the failure modes of Week 8's trajectory grader, offline.

    Exploratory: that grader was written for one agent. Its rules (a tool the task needs was never called, a call repeated,
    a date nobody supplied) are applied to the calls of the whole team as if one agent had made them, so a mode can be a
    side effect of the split, for example a date the manager rewrote before the calculator saw it."""
    tasks = tasks if tasks is not None else get_tasks(include_probes=True)
    out = {}
    for arm in arms:
        graded = trajectory.grade_all([path_view(run) for run in results["runs"] if run["approach"] == arm], tasks)
        out[arm] = {"runs": len(graded), "gap": trajectory.gap_table(graded), "modes": trajectory.mode_counts(graded)}
    return out


def cost_ratio_bounds(baseline, other):
    """For ANY non-negative prices, the cost of `other` divided by the cost of `baseline` lies between the input-token
    ratio and the output-token ratio (a weighted average of the two). None when a baseline count is zero, or when either arm has no runs
    (an arm that never ran has no cost to compare)."""
    if baseline.get("runs", 1) == 0 or other.get("runs", 1) == 0 or not baseline["prompt_mean"] or not baseline["completion_mean"]:
        return None
    ratios = (other["prompt_mean"] / baseline["prompt_mean"], other["completion_mean"] / baseline["completion_mean"])
    return min(ratios), max(ratios)


def clean_units(results, first=AGENT, second=TEAM, drop_limits=True):
    """The results cut down to the units where both arms ran and neither hit a limit or a provider problem, and what was dropped.

    A unit is one task and repeat. Dropping every unit in which ANY agent of either arm ended on a step, token, time or
    repeat limit, or on a provider problem (an error, a spent quota or an empty reply: a reply with no text and no tool request),
    shows whether the caps and the provider, rather than the designs, decided the result.
    With drop_limits=False only the provider problems and the incomplete units go (the prediction counts limit stops itself).
    """
    by_cell = {}
    for run in results["runs"]:
        if run["approach"] in (first, second):
            by_cell.setdefault((run["task_id"], run["repeat"]), {})[run["approach"]] = run
    keep, dropped_limits, dropped_trouble, incomplete = set(), 0, 0, 0
    for cell, runs in by_cell.items():
        if first not in runs or second not in runs:
            incomplete += 1
        elif any(provider_trouble(run) for run in runs.values()):
            dropped_trouble += 1
        elif drop_limits and any(hit_limit(run) for run in runs.values()):
            dropped_limits += 1
        else:
            keep.add(cell)
    kept = [run for run in results["runs"] if run["approach"] in (first, second) and (run["task_id"], run["repeat"]) in keep]
    return ({"meta": dict(results["meta"], arms=[first, second], approaches=[first, second]), "runs": kept},
            {"units": len(by_cell), "kept": len(keep), "dropped_for_limits": dropped_limits, "dropped_for_provider": dropped_trouble,
             "incomplete": incomplete})


# ---------------------------------------------------------------------------- how the race was run

def _resume_stamp(entry):
    """When a resumed session started: a dict with 'at' (the current script) or a plain timestamp (an older one)."""
    return entry.get("at") if isinstance(entry, dict) else entry


def calendar_days(meta):
    """The distinct calendar dates (YYYY-MM-DD, as written) of the race's start and of each resume, oldest first. A stamp that is not a date is ignored."""
    stamps = [meta.get("started")] + [_resume_stamp(entry) for entry in meta.get("resumed") or []]
    return sorted({stamp[:10] for stamp in stamps if isinstance(stamp, str) and _DATE_RE.match(stamp)})


def _describe_resume(entry):
    if not isinstance(entry, dict):
        return str(entry)
    details = []
    if entry.get("arms_added"):
        details.append("added " + ", ".join(entry["arms_added"]))
    if entry.get("model"):
        details.append(f"model {entry['model']}")
    if entry.get("rpm") is not None:
        details.append(f"{entry['rpm']} calls a minute")
    return str(entry.get("at") or "?") + (f" ({'; '.join(details)})" if details else "")


def _interleaving(meta):
    """The sentence about run order: interleaved, except any arm a resume added after the others had run."""
    said = "; runs interleaved, the order rotating" if meta.get("interleaved") else ""
    late = meta.get("not_interleaved_arms") or []
    if late:
        said += f"{',' if said else ';'} except {', '.join(late)}, which ran after the others (added by a resume) and so were not interleaved with them"
    return said


def history_lines(meta):
    """Header lines on how the race was run, each only when the file records it (older files do not): resumes with the rate limit and
    model of each session, runs set aside after an outage, the code stamp of each session, and the prediction document's hash."""
    lines, resumed = [], meta.get("resumed") or []
    if resumed:
        lines.append(f"resumed {len(resumed)} time{'' if len(resumed) == 1 else 's'}: " + "; ".join(_describe_resume(entry) for entry in resumed))
        rates = sorted({rate for rate in [meta.get("llm_rpm")] + [e.get("rpm") for e in resumed if isinstance(e, dict)]
                        if isinstance(rate, int) and not isinstance(rate, bool)})
        if len(rates) > 1:
            lines.append(f"WARNING: the sessions ran at different rate limits ({' and '.join(str(rate) for rate in rates)} calls a minute), "
                         "so wall-clock seconds are not comparable across them")
        requested = sorted({model for model in (meta.get("models") or {}).values() if model})
        for entry in resumed:
            if isinstance(entry, dict) and entry.get("model") and requested and entry["model"] not in requested:
                lines.append(f"WARNING: the session at {entry.get('at') or '?'} used model {entry['model']}, not {' or '.join(requested)}")
    aside = len(meta.get("set_aside_runs") or [])
    if aside:
        lines.append(f"{aside} run{' was' if aside == 1 else 's were'} set aside after a provider outage and run again (kept verbatim in the saved file, outside the runs counted below)")
    history = [entry for entry in meta.get("code_history") or [] if isinstance(entry, dict)]
    if history:
        codes = [entry.get("code") or {} for entry in history]
        changed = sorted({key for code in codes[1:] for key in set(code) | set(codes[0]) if code.get(key) != codes[0].get(key)})
        same = "the code was the same in every session" if not changed else \
            f"the code was not the same in every session (differs from the first stamp in: {', '.join(changed)})"
        stamps = "; ".join(f"{entry.get('at') or '?'} git {code.get('git', '?')}" for entry, code in zip(history, codes))
        lines.append(f"code history: {len(history)} stamp{'' if len(history) == 1 else 's'} ({stamps}); {same}")
    if meta.get("prediction_doc"):
        lines.append(f"prediction document (docs/week10/prediction.md): git blob {meta['prediction_doc']}, recorded when the race started")
    return lines


def closing_text(meta, stats):
    """The paragraph that ends the report: what the numbers cannot tell you, with what the race file and the numbers say filled in, so that
    no sentence asserts something about the data that the data does not show."""
    days = calendar_days(meta)
    when = (f"this race spanned a quota reset (it ran on {len(days)} calendar days: {', '.join(days)}), so it is one model but not one day, "
            "drift between the days is in the comparison, and it is one run of the race" if len(days) > 1
            else "this is one model on one day and one run of the race")
    counts = [row["runs"] for row in stats.values()]
    size = (f"Each arm has {counts[0]} run{'' if counts[0] == 1 else 's'}" if counts and len(set(counts)) == 1
            else f"The arms have {', '.join(str(n) for n in counts)} runs")
    near_ceiling = AGENT in stats and stats[AGENT]["runs"] and stats[AGENT]["success_rate"] >= NEAR_CEILING
    rate = meta.get("llm_rpm")
    parts = [f"Read before quoting a number: {when}, so variation between races is not measured.",
             f"{size} and the repeats of a task are correlated, so quality is described, not ranked: a gap smaller than the intervals "
             "and the McNemar p allow is not resolved" + (", and with the single agent near the ceiling only a loss can show." if near_ceiling else "."),
             "The team and the single agent differ in more than one thing (prompts, the split of tools, a manager that must rephrase the "
             "question, per-agent step limits), so this compares THIS team with the Week 7 agent as it stands, not multi-agent with "
             "single-agent in general."]
    if rate:
        parts.append(f"With a rate limit of {rate} calls a minute, wall-clock time is mostly the shared rate limiter, and a timeout is probably the "
                     "limiter unless model seconds alone exceed the budget.")
    parts.append("Parallel hand-offs were not tried. Tokens are the provider's own counts. Dollars are only as good as the prices you state. "
                 "The verdict is yours to write in docs/week10/findings.md.")
    return " ".join(parts)


# ---------------------------------------------------------------------------- the whole comparison

def summary(results, input_price=None, output_price=None):
    """Every number the report prints, as one dict (so a test can check them and a script can reuse them)."""
    input_price, output_price = _stated(input_price), _stated(output_price)
    arms = arm_names(results)
    stats = {arm: arm_stats(results, arm, input_price, output_price) for arm in arms}
    out = {"arms": arms, "stats": stats, "prices": pricing.describe_prices(input_price, output_price),
           "priced": pricing.is_priced(input_price, output_price), "per_task": per_task(results, arms),
           "failed": failed_runs(results, arms), "instrument": {arm: instrument_stats(results, arm) for arm in arms},
           "path": path_stats(results, arms)}
    out["served_models_differ"] = len({tuple(row["served"]) for row in out["instrument"].values() if row["served"]}) > 1
    out["internal_errors"] = sum(row["internal_errors"] for row in out["instrument"].values())
    if AGENT in stats and TEAM in stats:
        single, crew = stats[AGENT], stats[TEAM]
        out["paired"] = paired(results, AGENT, TEAM)
        out["paired_by_task"] = paired_by_task(results, AGENT, TEAM)
        out["per_agent"] = per_agent_stats(results, TEAM)
        out["team_by_task"] = team_by_task(results, TEAM)
        out["cost_ratio_bounds"] = cost_ratio_bounds(single, crew)
        out["team_over_agent"] = _ratios(crew, single)
        clean, dropped = clean_units(results)
        out["clean"] = {"dropped": dropped, "paired": paired(clean), "paired_by_task": paired_by_task(clean),
                        "stats": {arm: arm_stats(clean, arm) for arm in (AGENT, TEAM)},
                        "team_over_agent": _ratios(arm_stats(clean, TEAM), arm_stats(clean, AGENT))}
    if AGENT in stats and NOISE in stats:
        out["calibration"] = {"paired": paired(results, AGENT, NOISE), "by_task": paired_by_task(results, AGENT, NOISE),
                              "noise_over_agent": _ratios(stats[NOISE], stats[AGENT])}
    return out


def _ratios(other, baseline):
    if not other["runs"] or not baseline["runs"]:                # an arm that never ran has no ratio: n/a, never 0.00x
        return {"calls": None, "tokens": None, "prompt": None, "completion": None, "model_seconds": None, "elapsed": None,
                "units": {r: None for r in PRICE_RATIOS}}
    return {"calls": ratio(other["calls_mean"], baseline["calls_mean"]), "tokens": ratio(other["tokens_mean"], baseline["tokens_mean"]),
            "prompt": ratio(other["prompt_mean"], baseline["prompt_mean"]),
            "completion": ratio(other["completion_mean"], baseline["completion_mean"]),
            "model_seconds": ratio(other["model_seconds_mean"], baseline["model_seconds_mean"]),
            "elapsed": ratio(other["elapsed_mean"], baseline["elapsed_mean"]),
            "units": {r: ratio(other["units_mean"][r], baseline["units_mean"][r]) for r in PRICE_RATIOS}}


def _x(value):
    return "n/a" if value is None else f"{value:.2f}x"


def _money(value):
    return "n/a" if value is None else f"${value:.5f}"


def _num(value, width, digits=0):
    return f"{'n/a':>{width}}" if value is None else f"{value:>{width}.{digits}f}"


_TYPOGRAPHIC = {0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x2013: "-", 0x2014: "-", 0x2026: "...", 0x00A0: " "}


def _ascii(text):
    """Plain ASCII for words a model wrote: curly quotes and dashes become the plain ones and anything else not ASCII becomes '?', so a report
    saved under docs/ stays plain. Only what is printed is changed; the saved runs keep the model's exact words."""
    return str(text).translate(_TYPOGRAPHIC).encode("ascii", "replace").decode("ascii")


def _no_runs(arm):
    return f"{arm:<9}n/a (no runs)"


def _quality_rows(stats, arms):
    rows = [f"{'arm':<9}{'runs':>5}{'success':>10}{'rate':>6}{'95% interval':>16}{'finished':>10}   stop reasons"]
    for arm in arms:
        row = stats[arm]
        if not row["runs"]:
            rows.append(_no_runs(arm))
            continue
        low, high = row["interval"]
        interval = f"[{low * 100:.0f}%, {high * 100:.0f}%]"
        won, done = f"{row['success']}/{row['runs']}", f"{row['finished']}/{row['runs']}"
        rows.append(f"{arm:<9}{row['runs']:>5}{won:>10}{row['success_rate'] * 100:>5.0f}%{interval:>16}{done:>10}   {row['stop_reasons']}")
    return rows


def _pair_line(pair, first, second, lead="paired by task and repeat"):
    return (f"{lead} ({pair['pairs']} pairs): both pass {pair['both']}, only {first} {pair['only_' + first]}, "
            f"only {second} {pair['only_' + second]}, neither {pair['neither']}; exact McNemar p = {pair['p']:.3f} "
            f"over {pair['only_' + first] + pair['only_' + second]} discordant pair(s); this treats the repeats of a task as independent, so it is optimistic")


def _tasks(count):
    return f"{count} task{'' if count == 1 else 's'}"


def _task_line(by_task, first, second):
    differing = by_task["more_" + first] + by_task["more_" + second]
    return (f"by task ({_tasks(by_task['tasks'])}): {first} passed more of the repeats on {_tasks(by_task['more_' + first])}, {second} on "
            f"{by_task['more_' + second]}, the same on {by_task['same']}; exact sign test over the {differing} differing task(s) p = {by_task['p']:.3f} "
            "(the task is the unit here, not the repeat)")


def format_report(results, input_price=None, output_price=None, price_source=None):
    """The report as printable lines: setup, caps, instrument, quality, speed, tokens, cost, the team, each task, and every failed run."""
    data, meta = summary(results, input_price, output_price), results["meta"]
    stats, arms = data["stats"], data["arms"]
    models = meta.get("models") or {}
    limits = meta.get("limits") or {}
    noise_late = "this arm ran after the others, so day-to-day drift is in it" if NOISE in (meta.get("not_interleaved_arms") or []) else ""
    lines = [f"=== Week 10 race '{meta.get('label', '?')}': {len(meta.get('tasks', []))} task(s) x {meta.get('repeats', '?')} repeat(s), "
             f"requested model {models.get(AGENT) or models.get(TEAM) or '?'} ===",
             f"arms: {', '.join(arms)}" + (f"   ({NOISE} is a second identical single-agent arm: a calibration of the method)" if NOISE in arms else "")
             + _interleaving(meta),
             f"limits per run: {limits.get('max_steps', '?')} steps, {limits.get('max_total_tokens', '?')} tokens, "
             f"{limits.get('timeout_seconds', '?')}s (the team shares ONE token and time budget; its step limits are per agent); "
             f"rate limit {meta.get('llm_rpm', '?')} calls a minute"]
    for arm, setting in (meta.get("config") or {}).items():
        lines.append(f"{arm}: " + ", ".join(f"{key} {value}" for key, value in setting.items()))
    if meta.get("code"):
        lines.append("code: " + ", ".join(f"{key} {value}" for key, value in meta["code"].items()))
    if meta.get("corpus"):
        lines.append(f"corpus: {len(meta['corpus'])} files, hashes " + ", ".join(f"{name} {digest}" for name, digest in meta["corpus"].items()))
    lines += history_lines(meta)
    if meta.get("caps"):
        lines += ["", "CAPS      what each agent may use. The team shares ONE token and time budget; its step limits are per agent, so its total number of model calls is not capped as a single agent's is",
                  f"{'arm':<10}{'agent':<12}{'steps':>6}{'tokens':>9}{'timeout':>9}{'calls per tool':>16}{'memory':>8}"]
        for row in meta["caps"]:
            lines.append(f"{row['arm']:<10}{row['agent']:<12}{row['steps']:>6}{str(row['tokens']):>9}{str(row['timeout']):>9}"
                         f"{row['calls per tool']:>16}{row['memory']:>8}")
        if meta.get("search"):
            lines.append("search tool, the same for every arm: " + ", ".join(f"{key} {value}" for key, value in meta["search"].items()))
    if not meta.get("complete", True):
        lines.append(f"PARTIAL: the race stopped early ({meta.get('stopped_because') or 'no reason recorded'}). Every number below is from the runs that finished.")
    if data["internal_errors"]:
        lines.append(f"INTERNAL ERRORS: {data['internal_errors']} hand-off(s) failed on a bug in the team code, not on the specialist. "
                     "Fix the cause and race again before reading any number below.")
    if data["served_models_differ"]:
        lines.append("WARNING: the arms were served by different models (see INSTRUMENT). The comparison is not like for like.")

    lines += ["", "INSTRUMENT   what the per-call records say about how each arm was measured",
              f"{'arm':<9}{'calls':>7}{'recorded':>10}{'retried':>9}{'wait of retried':>17}{'errors':>8}{'total != p+c':>14}{'cached':>8}{'reasoning':>11}   served by"]
    for arm in arms:
        row = data["instrument"][arm]
        if not row["runs"]:
            lines.append(_no_runs(arm))
            continue
        recorded = f"{row['recorded']}/{row['runs']}"
        lines.append(f"{arm:<9}{row['calls']:>7}{recorded:>10}{row['retried']:>9}{row['retry_wait']:>16.1f}s{row['errors']:>8}"
                     f"{row['unexplained_tokens']:>14}{row['cached_tokens']:>8}{row['reasoning_tokens']:>11}   {', '.join(row['served']) or 'not recorded'}")
    for arm in arms:
        row = data["instrument"][arm]
        if row["unexplained_abs"] != abs(row["unexplained_tokens"]):         # gaps of both signs cancel in the column above
            lines.append(f"{arm}: the provider's totals differ from prompt + completion in both directions (net {row['unexplained_tokens']:+d}, "
                         f"{row['unexplained_abs']} in absolute value), so the column above nets them")
    lines.append("total != p+c = tokens a provider's own total counts beyond prompt plus completion (hidden thinking, for one): those are NOT in the token numbers "
                 "below, so a real bill could differ. wait of retried = seconds of rate-limit pauses and back-off in calls that needed more than one attempt "
                 "(not only the back-off). cached = the part of the prompt served from a cache: those tokens ARE inside the prompt counts below, and a provider "
                 "may bill them at a lower rate.")

    lines += ["", "QUALITY   success = the run finished AND passed the rule checks"] + _quality_rows(stats, arms)
    lines.append("the 95% interval treats every run as an independent trial, but the repeats of a task are correlated, so it is optimistic")
    if "paired" in data:
        pair = data["paired"]
        lines += [_pair_line(pair, AGENT, TEAM), _task_line(data["paired_by_task"], AGENT, TEAM)]
        if pair["unpaired"]:
            lines.append(f"not paired (only one arm has a run, left out of the pairs): {', '.join(pair['unpaired'])}")
        lines.append("a difference is only called when the exact p is below 0.05, and with fewer than 6 discordant pairs it cannot be: "
                     "at this number of runs a gap of one or two runs is not resolved. Read the by-task line first: the pair line counts "
                     "the near-copy repeats of a task as separate trials")
    if "calibration" in data:
        lines += [_pair_line(data["calibration"]["paired"], AGENT, NOISE,
                             f"calibration, {AGENT} against {NOISE} (the same design twice{', but ' + noise_late if noise_late else ''}), paired by task and repeat"),
                  _task_line(data["calibration"]["by_task"], AGENT, NOISE)]
    any_limit = "any agent's limit"
    lines += ["", "STOPS     runs that ended on a limit themselves, runs in which any agent hit a limit (a specialist's cap the manager worked around counts "
                  "here), and runs with provider trouble: the SENSITIVITY section below drops the units that have either",
              f"{'arm':<9}{'own limit':>11}{any_limit:>20}{'provider trouble':>18}"]
    for arm in arms:
        row = stats[arm]
        lines.append(_no_runs(arm) if not row["runs"] else f"{arm:<9}{row['own_limit_stops']:>11}{row['limit_stops']:>20}{row['provider_trouble']:>18}")

    lines += ["", "SPEED     per run. Model seconds are time inside model calls. Wall seconds include queueing behind the previous run's calls in the shared rate limiter",
              f"{'arm':<9}{'calls':>7}{'max':>5}{'>8':>4}{'>12':>5}{'model s mean':>14}{'median':>8}{'max':>7}{'wall s mean':>13}{'median':>8}{'max':>7}{'waiting':>9}{'limiter s':>11}"]
    for arm in arms:
        row = stats[arm]
        if not row["runs"]:
            lines.append(_no_runs(arm))
            continue
        limiter = ratio(row["calls_mean"] * 60, meta["llm_rpm"]) if meta.get("llm_rpm") else None
        lines.append(f"{arm:<9}{row['calls_mean']:>7.1f}{row['calls_max']:>5}{row['calls_over_8']:>4}{row['calls_over_12']:>5}"
                     f"{row['model_seconds_mean']:>14.1f}{row['model_seconds_median']:>8.1f}{row['model_seconds_max']:>7.1f}"
                     f"{row['elapsed_mean']:>13.1f}{row['elapsed_median']:>8.1f}{row['elapsed_max']:>7.1f}{row['wait_mean']:>9.1f}{_num(limiter, 11, 1)}")
    lines.append("limiter s = calls x 60 / the rate limit: the seconds a run's calls take to get through the limiter, what the free tier charges in time. "
                 "The team calls the model one agent at a time.")

    lines += ["", "TOKENS    per run, prompt and completion apart. Prompt tokens split into opening + later (measured)",
              f"{'arm':<9}{'prompt':>8}{'completion':>12}{'total':>8}{'median':>8}{'max':>8}{'opening':>9}{'later':>8}{'per pass':>10}"]
    for arm in arms:
        row = stats[arm]
        if not row["runs"]:
            lines.append(_no_runs(arm))
            continue
        lines.append(f"{arm:<9}{row['prompt_mean']:>8.0f}{row['completion_mean']:>12.0f}{row['tokens_mean']:>8.0f}{row['tokens_median']:>8.0f}"
                     f"{row['tokens_max']:>8.0f}{row['opening_mean']:>9.0f}{row['later_mean']:>8.0f}{_num(row['tokens_per_success'], 10)}")
    lines.append("opening = the first call of every conversation (a team opens one per hand-off). later = every other call's prompt: the conversation "
                 "so far sent again plus whatever the step added, so an upper bound on re-sent text. per pass = total tokens divided by passing runs.")
    if TEAM in stats and stats[TEAM]["runs"]:
        crew = stats[TEAM]
        lines.append(f"derived: had every hand-off carried the manager's whole conversation, the team would have sent between "
                     f"{crew['forwarded_floor_mean']:.0f} and {crew['forwarded_extra_mean']:.0f} more prompt tokens per run "
                     f"({ratio(crew['forwarded_floor_mean'], crew['prompt_mean']) or 0:.0%} to {ratio(crew['forwarded_extra_mean'], crew['prompt_mean']) or 0:.0%} "
                     f"on top of its {crew['prompt_mean']:.0f}): an estimate between a floor (the manager's history only) and a ceiling (its whole prompt, "
                     "tool list included, which forwarding would not carry), not a lower bound; the measured team hands over only the sub-question")
        lines.append(f"derived: the manager re-reads the specialists' answers on its later calls, at most about {crew['reread_mean']:.0f} prompt tokens per run "
                     "(memory shortens older tool results, which this does not subtract)")
    for arm in arms:
        if stats[arm]["no_step_runs"]:
            lines.append(f"derived: {arm}: {stats[arm]['no_step_tokens']} tokens over {stats[arm]['no_step_runs']} run(s) were billed in model calls that left "
                         "no step record (a provider reply with no choices), so the opening and later columns above leave them out")

    lines += ["", "COST      relative units: an input token is 1 unit, an output token is r units. No price is assumed: read the column whose r is nearest "
                  "the ratio of the output price to the input price you state",
              f"{'arm':<9}" + "".join(f"{f'r={r} per run':>{UNIT_WIDTH}}" for r in PRICE_RATIOS)]
    for arm in arms:
        lines.append(_no_runs(arm) if not stats[arm]["runs"] else f"{arm:<9}" + "".join(_num(stats[arm]["units_mean"][r], UNIT_WIDTH) for r in PRICE_RATIOS))
    lines.append(f"{'per pass':<9}" + "".join(f"{f'r={r}':>{UNIT_WIDTH}}" for r in PRICE_RATIOS))
    for arm in arms:
        lines.append(_no_runs(arm) if not stats[arm]["runs"] else f"{arm:<9}" + "".join(_num(stats[arm]["units_per_success"][r], UNIT_WIDTH) for r in PRICE_RATIOS))
    bounds = data.get("cost_ratio_bounds")
    if bounds:
        ratios = data["team_over_agent"]
        lines.append(f"{TEAM} / {AGENT} in cost units: " + ", ".join(f"r={r} {_x(ratios['units'][r])}" for r in PRICE_RATIOS)
                     + f". Whatever the prices, between {_x(bounds[0])} and {_x(bounds[1])} "
                     f"(input tokens {_x(ratios['prompt'])}, output tokens {_x(ratios['completion'])}) for one input price and one output price; "
                     "a cheaper price for cached input is a third price, which this bound does not cover")
    requested = models.get(AGENT) or models.get(TEAM) or "?"
    lines.append("free-tier cost (derived; requests are what a free key is spent in): " + "; ".join(
        f"{arm} n/a (no runs)" if not row["runs"] else
        f"{arm} {row['requests_mean']:.1f} requests a run, {_num(row['runs_per_day'], 0).strip()} runs in a {DAILY_REQUESTS}-request day"
        for arm, row in stats.items()))
    lines.append("a request is every attempt in the per-call records when they are kept (retries and failed calls included), else the successful calls only. "
                 f"The {DAILY_REQUESTS}-request day is the lite-model figure measured in Week 8 (docs/week8); the model raced here, {requested}, may allow another number.")
    lines.append(f"DOLLARS   prices: {data['prices']}" + (f"; source: {price_source}" if price_source and data["priced"] else ""))
    if data["priced"]:
        lines.append(f"{'arm':<9}{'per run':>12}{'per 1,000 runs':>17}{'per passing run':>18}")
        for arm in arms:
            row = stats[arm]
            per_thousand = None if row["cost_mean"] is None else row["cost_mean"] * 1000
            lines.append(_no_runs(arm) if not row["runs"] else
                         f"{arm:<9}{_money(row['cost_mean']):>12}{'n/a' if per_thousand is None else f'${per_thousand:.2f}':>17}{_money(row['cost_per_success']):>18}")
    if "team_over_agent" in data:
        ratios = data["team_over_agent"]
        lines += ["", f"{TEAM} / {AGENT}:  calls {_x(ratios['calls'])}, tokens {_x(ratios['tokens'])}, model seconds {_x(ratios['model_seconds'])}, "
                      f"wall seconds {_x(ratios['elapsed'])} (ratios of the arms' means)"]
    if "calibration" in data:
        ratios = data["calibration"]["noise_over_agent"]
        lines.append(f"{NOISE} / {AGENT}:  calls {_x(ratios['calls'])}, tokens {_x(ratios['tokens'])}, model seconds {_x(ratios['model_seconds'])}, "
                     f"wall seconds {_x(ratios['elapsed'])}   (the same design twice: how far apart chance puts two arms{'; ' + noise_late if noise_late else ''})")
    if "per_agent" in data and data["per_agent"]["runs"]:
        crew = data["per_agent"]
        lines += ["", f"THE TEAM, BY AGENT   over {crew['runs']} run(s)",
                  f"{'agent':<12}{'calls':>7}{'prompt':>9}{'completion':>12}{'tokens':>9}{'share':>7}{'model s':>9}{'hand-offs':>11}{'calls each':>12}"]
        for agent, row in crew["agents"].items():
            lines.append(f"{agent:<12}{row['calls']:>7}{row['prompt_tokens']:>9}{row['completion_tokens']:>12}{row['tokens']:>9}"
                         f"{row['token_share'] * 100:>6.0f}%{row['api_seconds']:>9.1f}{row['handoffs']:>11}{_num(row['calls_per_handoff'], 12, 1)}")
        lines.append(f"hand-offs by how they ended: {crew['handoff_states'] or 'none'}")
        lines.append(f"hand-offs by stop reason (agent:state:stop reason): {crew['handoff_stops'] or 'none'}")
        saving, together, team_runs = stats[TEAM]["overlap_saving_mean"], stats[TEAM]["side_by_side_runs"], stats[TEAM]["runs"]
        lines.append("derived: hand-offs the manager asked for in the same step could have overlapped; had they, a run would have taken "
                     f"{saving:.1f} seconds less elapsed time on average (model seconds would not change, and the free tier's rate limiter would serialise the calls anyway)"
                     + (" (the manager asked for one at a time)" if not together else f" ({together} of {team_runs} runs asked for two or more at once)"))
        lines += ["", "THE TEAM, BY TASK   mean hand-offs and model calls per run",
                  f"{'task':<24}{'shape':<13}{'researcher':>11}{'calculator':>11}{'calls: mgr':>12}{'res':>6}{'calc':>6}"]
        for task, cell in data["team_by_task"].items():
            lines.append(f"{task:<24}{task_shape(task):<13}{cell['handoffs']['researcher']:>11.1f}{cell['handoffs']['calculator']:>11.1f}"
                         f"{cell['calls']['manager']:>12.1f}{cell['calls']['researcher']:>6.1f}{cell['calls']['calculator']:>6.1f}")
    lines += ["", "PER TASK  shape, then successes out of runs, mean calls, mean tokens" + (f"; last column {TEAM} / {AGENT} in tokens" if "paired" in data else "")]
    lines.append(f"{'task':<24}{'shape':<13}" + "".join(f"{arm:>10} ok{'calls':>6}{'tokens':>8}" for arm in arms) + ("   ratio" if "paired" in data else ""))
    for task, cells in data["per_task"].items():
        row = f"{task:<24}{cells['shape']:<13}"
        for arm in arms:
            cell = cells.get(arm)
            row += f"{cell['ok']:>10}/{cell['runs']:<2}{cell['calls']:>6.1f}{cell['tokens']:>8.0f}" if cell else f"{'-':>10}   {'-':>6}{'-':>8}"
        if "paired" in data and cells.get(AGENT) and cells.get(TEAM):
            row += f"{_x(ratio(cells[TEAM]['tokens'], cells[AGENT]['tokens'])):>8}"
        lines.append(row)

    lines += ["", "BEHAVIOUR   what the answers and paths look like, apart from the rule checks",
              f"{'arm':<9}{'answer chars':>14}{'documents cited':>17}{'refused':>9}{'refused, no search':>20}{'answered, no hand-off':>23}{'duplicate searches':>20}"]
    for arm in arms:
        row = stats[arm]
        if not row["runs"]:
            lines.append(_no_runs(arm))
            continue
        lines.append(f"{arm:<9}{row['answer_chars_mean']:>14.0f}{row['documents_mean']:>17.1f}{row['refused']:>9}{row['refused_without_searching']:>20}"
                     f"{_num(row['answered_without_hand_off'], 23)}{row['duplicate_searches_mean']:>20.2f}")
    lines += ["", "PATH   (exploratory) Week 8's path grader, offline, with the manager's hand-off calls dropped. It was written for ONE agent, so a mode can be a side effect of the split",
              f"{'arm':<9}{'runs':>5}{'right, right path':>19}{'right, wrong path':>19}{'wrong, right path':>19}{'wrong, wrong path':>19}   modes (runs showing each)"]
    for arm in arms:
        row = data["path"][arm]
        if not stats[arm]["runs"]:
            lines.append(_no_runs(arm))
            continue
        gap = row["gap"]
        lines.append(f"{arm:<9}{row['runs']:>5}{gap['right-answer-right-path']:>19}{gap['right-answer-wrong-path']:>19}{gap['wrong-answer-right-path']:>19}"
                     f"{gap['wrong-answer-wrong-path']:>19}   {row['modes'] or 'none'}")
    if "clean" in data:
        clean, dropped = data["clean"], data["clean"]["dropped"]
        lines += ["", f"SENSITIVITY   the same comparison with every unit dropped in which any agent of either arm hit a limit or a provider problem "
                      f"(an error, a spent quota or an empty reply) ({dropped['kept']} of {dropped['units']} units kept: {dropped['dropped_for_limits']} dropped for limits, "
                      f"{dropped['dropped_for_provider']} for the provider, {dropped['incomplete']} incomplete)"]
        lines += _quality_rows(clean["stats"], (AGENT, TEAM))
        lines += [_pair_line(clean["paired"], AGENT, TEAM), _task_line(clean["paired_by_task"], AGENT, TEAM)]
        ratios = clean["team_over_agent"]
        lines.append(f"{TEAM} / {AGENT} on these units:  calls {_x(ratios['calls'])}, tokens {_x(ratios['tokens'])}, model seconds {_x(ratios['model_seconds'])}")
    lines += ["", f"FAILED RUNS   every run that did not succeed ({len(data['failed'])})"]
    for failed in data["failed"]:
        lines.append(f"  {failed['task']:<24}{failed['arm']:<9}repeat {failed['repeat']}  stopped: {failed['stop_reason']}")
        if failed["failed_checks"]:
            lines.append(f"      failed checks: {_ascii('; '.join(failed['failed_checks']))}")
        if failed["answer"]:
            lines.append(f"      answer: {_ascii(' '.join(failed['answer'].split()))}")
    lines += ["", closing_text(meta, stats)]
    return lines
