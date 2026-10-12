"""Check the pre-registered prediction for the team race against a saved race (Week 10).

Before the race was run, `docs/week10/prediction.md` wrote down what the team should do and what would
count as the prediction failing. This turns those sentences into arithmetic over the saved race, so nobody has to
decide afterwards whether the prediction held. The thresholds below are copied from that document and change only if
that document does, and that document was committed before the first race run.

Every prediction is about a MEASURED quantity; none says which design to ship. The verdict about which design to use
is yours to write.

Where the numbers come from. Anchor 1, `evals/results/race-race.json`, the Week 7 race of the single agent on these nine
tasks: 3.5 model calls and 4,220 tokens a run, 704 of the tokens the opening of its one conversation. Anchor 2, a model of
the hand-offs on that tool mix (scripts/race_team.py --plan): 6.1 to 8.4 team calls a run (4 if every task were a single
lookup, which needs a manager call, a search, a researcher answer and a manager answer). Anchor 3, two pilots on 14 questions
that are NOT race tasks (evals/results/pilot-1.json and pilot-2.json, listed in CHANGES.md): the single agent made 2.4 calls
and 2,300 tokens a run, the team 4.6 calls and 3,300 tokens a run, so the team's calls are smaller (about 730 tokens a call
against 980). The bands: calls 1.3 to 3.0 times (6.1 / 3.5 = 1.7 up to 8.4 / 3.5 = 2.4, widened on both sides because the model is a
guess), tokens 0.8 to 2.0 times (the 730 tokens a call times 6.1 to 8.4 calls, over 4,220, is 1.1 to 1.5, widened the same way),
model seconds 1.0 to 3.0 times (they follow the calls).

The predictions, read on the units both arms completed (a unit is a task and a repeat):
  P1  calls: the team makes between 1.3 and 3.0 times the single agent's model calls per run, and more of them on at
      least 7 of the 9 tasks
  P2  tokens: the team uses between 0.8 and 2.0 times the single agent's total tokens per run
  P3  model seconds: between 1.0 and 3.0 times the single agent's model seconds per run
  P4  the calculator is handed work in at least 6 of the 9 runs of the three tasks that need a calculation
      (t7-carry-forward-sum, t7-notice-end-date, t7-leave-end-date) and in at most 4 of the other 18 runs
  P5  on those three tasks the team passes at least as many runs as the single agent minus 2
  P6  over all tasks the team passes at least as many runs as the single agent minus 5
  P7  the manager asks for one hand-off at a time in at least 70% of the team's runs
  P8  the opening tokens (the first call of every conversation) of the team are at least 1.5 times the single agent's
  P9  at most 3 team runs and at most 2 single-agent runs end on a limit (steps, tokens, time or a repeated call): a run's own
      stop reason; a team run in which a hand-off hit a limit and the manager still finished is reported beside it, not counted
  P10 on the unanswerable task the team refuses every time and never needs more than 12 model calls
The prediction has FAILED if P1, P2, P3 or P6 does not hold. The others are reported held or not held, with no verdict
on the whole. Units where any run ended on a provider problem (an error, a spent quota or an empty reply) or carried a usage
warning, and units where an arm is missing, are dropped and counted. The thresholds are registered for 9 tasks x 3 repeats,
27 units: a race that is incomplete, or that leaves a different number of usable units, gets a PARTIAL banner and no verdict.
P1, P2, P3 and P8 are compared at the two decimals the report prints. Every analysis not listed here is exploratory.
"""
from evals import team_report
from evals.team_report import AGENT, TEAM

BANDS = {"calls": (1.3, 3.0), "tokens": (0.8, 2.0), "model_seconds": (1.0, 3.0)}
MORE_CALLS_ON_AT_LEAST = 7              # of the nine tasks
CALCULATOR_TASKS = ("t7-carry-forward-sum", "t7-notice-end-date", "t7-leave-end-date")
CALCULATOR_MIN_ON_THEM, CALCULATOR_MAX_ELSEWHERE = 6, 4
PASS_MARGIN_CALCULATION, PASS_MARGIN_ALL = 2, 5
ONE_AT_A_TIME_SHARE = 0.70
OPENING_FACTOR = 1.5
MAX_LIMIT_STOPS = {TEAM: 3, AGENT: 2}
UNANSWERABLE, MAX_CALLS_UNANSWERABLE = "t7-unanswerable", 12
FAILS_IF = ("P1", "P2", "P3", "P6")
REGISTERED_TASKS, REGISTERED_REPEATS = 9, 3
REGISTERED_UNITS = REGISTERED_TASKS * REGISTERED_REPEATS       # the units every threshold above was registered for
ABSOLUTE_COUNT_ROWS = ("P1", "P4", "P5", "P6", "P9")           # thresholds that count runs or tasks, so they only mean something on that size
NO_DATA = None                                                 # what a check returns as `held` when the number it needs has a zero denominator


def _passes(runs):
    return sum(bool(run["success"]) for run in runs)


def _band(key, name):
    low, high = BANDS[name]

    def check(clean, _runs):
        value = team_report.ratio(clean["stats"][TEAM][key], clean["stats"][AGENT][key])
        if value is None:
            return NO_DATA, f"n/a, no data: the single agent's figure is zero (band {low} to {high})"
        shown = f"{value:.2f}"                          # compare what is printed, so a value shown as 1.30x is never called outside 1.3 to 3.0
        return low <= float(shown) <= high, f"{shown}x (band {low} to {high}; compared at the two decimals shown)"
    return check


def _p1(clean, _runs):
    ratio_held, evidence = _band("calls_mean", "calls")(clean, None)
    tasks = team_report.per_task(clean["results"], (AGENT, TEAM))
    more = [task for task, cells in tasks.items() if AGENT in cells and TEAM in cells and cells[TEAM]["calls"] > cells[AGENT]["calls"]]
    held = NO_DATA if ratio_held is NO_DATA else ratio_held and len(more) >= MORE_CALLS_ON_AT_LEAST
    return held, f"{evidence}; more calls on {len(more)} of {len(tasks)} tasks (needs {MORE_CALLS_ON_AT_LEAST})"


def _p4(clean, runs):
    team_runs = [run for run in runs if run["approach"] == TEAM and run.get("team")]
    asked = lambda run: run["team"]["per_agent"]["calculator"]["handoffs"] > 0         # noqa: E731
    on = [run for run in team_runs if run["task_id"] in CALCULATOR_TASKS]
    elsewhere = [run for run in team_runs if run["task_id"] not in CALCULATOR_TASKS]
    used_on, used_elsewhere = sum(asked(run) for run in on), sum(asked(run) for run in elsewhere)
    held = used_on >= CALCULATOR_MIN_ON_THEM and used_elsewhere <= CALCULATOR_MAX_ELSEWHERE
    if not on or not elsewhere:                         # a count out of no runs is no data, not a pass or a fail
        held = NO_DATA
    return held, (f"calculator handed work in {used_on} of {len(on)} runs of the calculation tasks (needs at least {CALCULATOR_MIN_ON_THEM}) "
                  f"and in {used_elsewhere} of {len(elsewhere)} other runs (at most {CALCULATOR_MAX_ELSEWHERE})")


def _passes_on(runs, arm, tasks):
    return _passes([run for run in runs if run["approach"] == arm and run["task_id"] in tasks])


def _p5(clean, runs):
    agent, crew = _passes_on(runs, AGENT, CALCULATOR_TASKS), _passes_on(runs, TEAM, CALCULATOR_TASKS)
    ran = {arm: any(run["approach"] == arm and run["task_id"] in CALCULATOR_TASKS for run in runs) for arm in (AGENT, TEAM)}
    held = crew >= agent - PASS_MARGIN_CALCULATION if all(ran.values()) else NO_DATA
    return held, f"team {crew}, single agent {agent} passes on the calculation tasks (team needs at least {agent - PASS_MARGIN_CALCULATION})"


def _p6(clean, runs):
    agent, crew = clean["stats"][AGENT]["success"], clean["stats"][TEAM]["success"]
    return crew >= agent - PASS_MARGIN_ALL, f"team {crew}, single agent {agent} passes (team needs at least {agent - PASS_MARGIN_ALL})"


def _p7(clean, runs):
    team_runs = [run for run in runs if run["approach"] == TEAM and run.get("team")]
    one_at_a_time = sum(not team_report.asked_side_by_side(run) for run in team_runs)       # from the hand-offs' structure, not their seconds
    share = one_at_a_time / len(team_runs) if team_runs else 0.0
    return (share >= ONE_AT_A_TIME_SHARE if team_runs else NO_DATA), f"{one_at_a_time} of {len(team_runs)} team runs ({share:.1%}; needs {ONE_AT_A_TIME_SHARE:.0%})"


def _p8(clean, runs):
    agent, crew = clean["stats"][AGENT]["opening_mean"], clean["stats"][TEAM]["opening_mean"]
    value = team_report.ratio(crew, agent)
    if value is None:
        return NO_DATA, f"n/a, no data: the single agent has no opening tokens (needs at least {OPENING_FACTOR}x)"
    shown = f"{value:.2f}"
    return float(shown) >= OPENING_FACTOR, f"{shown}x (needs at least {OPENING_FACTOR}x; compared at the two decimals shown)"


def _p9(clean, runs):
    stops = {arm: clean["stats"][arm]["own_limit_stops"] for arm in (TEAM, AGENT)}       # a run ENDS on a limit when its own stop reason is one
    recovered = clean["stats"][TEAM]["limit_stops"] - stops[TEAM]
    return all(stops[arm] <= MAX_LIMIT_STOPS[arm] for arm in stops), \
        (f"team {stops[TEAM]} (at most {MAX_LIMIT_STOPS[TEAM]}), single agent {stops[AGENT]} (at most {MAX_LIMIT_STOPS[AGENT]}); a run counts when its own "
         f"stop reason is a limit, and {recovered} more team run(s) had a hand-off stop on a limit and ended another way (not counted)")


def _p10(clean, runs):
    team_runs = [run for run in runs if run["approach"] == TEAM and run["task_id"] == UNANSWERABLE]
    refused = sum(team_report.answer_features(run)["refused"] for run in team_runs)
    longest = max((run["llm_calls"] for run in team_runs), default=0)
    held = refused == len(team_runs) and longest <= MAX_CALLS_UNANSWERABLE if team_runs else NO_DATA
    return held, f"refused {refused} of {len(team_runs)}, most model calls in one run {longest} (at most {MAX_CALLS_UNANSWERABLE})"


PREDICTIONS = [
    ("P1", "the team makes 1.3 to 3.0 times the single agent's model calls per run, and more on at least 7 of the 9 tasks", "ratio of mean calls per run", _p1),
    ("P2", "the team uses 0.8 to 2.0 times the single agent's total tokens per run", "ratio of mean total tokens per run", _band("tokens_mean", "tokens")),
    ("P3", "the team spends 1.0 to 3.0 times the single agent's model seconds per run", "ratio of mean model seconds per run", _band("model_seconds_mean", "model_seconds")),
    ("P4", "the calculator is handed work in at least 6 of the 9 calculation-task runs and at most 4 of the other 18", "runs with a calculator hand-off", _p4),
    ("P5", "on the three calculation tasks the team passes at least as many runs as the single agent minus 2", "passing runs on those tasks", _p5),
    ("P6", "over all tasks the team passes at least as many runs as the single agent minus 5", "passing runs", _p6),
    ("P7", "the manager asks for one hand-off at a time in at least 70% of the team's runs", "runs with no overlapping hand-offs", _p7),
    ("P8", "the team's opening tokens are at least 1.5 times the single agent's", "ratio of mean opening tokens per run", _p8),
    ("P9", "at most 3 team runs and at most 2 single-agent runs end on a limit", "runs that ended on a limit", _p9),
    ("P10", "on the unanswerable task the team refuses every time with at most 12 model calls", "refusals and calls on t7-unanswerable", _p10),
]


def registered_size_problems(results, dropped, usable):
    """Why this race is not the 9 tasks x 3 repeats the thresholds were registered for, as sentences (empty when it is)."""
    meta = results.get("meta") or {}
    problems = []
    if not meta.get("complete", True):
        problems.append(f"the race is incomplete, it stopped: {meta.get('stopped_because') or 'no reason recorded'}")
    if dropped["kept"] != REGISTERED_UNITS:
        problems.append(f"{dropped['kept']} usable units, not {REGISTERED_UNITS}: {dropped['dropped_for_provider']} dropped for a provider problem, "
                        f"{dropped['incomplete']} incomplete")
    planned = meta.get("tasks")
    if planned is not None and len(planned) != REGISTERED_TASKS:
        problems.append(f"{len(planned)} tasks in the plan, not {REGISTERED_TASKS}")
    read = len({run["task_id"] for run in usable})
    if read != REGISTERED_TASKS:
        problems.append(f"the usable units cover {read} task(s), not {REGISTERED_TASKS}")
    if meta.get("repeats") is not None and meta["repeats"] != REGISTERED_REPEATS:
        problems.append(f"{meta['repeats']} repeats, not {REGISTERED_REPEATS}")
    return problems


def _status(held, partial):
    if held is NO_DATA:
        return "no data"                                # a number that does not exist cannot be partial
    return "partial" if partial else ("held" if held else "not held")


def check_prediction(results):
    """(rows, failed, dropped): each prediction on the clean units, whether the whole prediction failed, and what was dropped.

    Each row has `status`: held, not held, partial (a count registered for 9 tasks x 3 repeats, read on a race that is not that
    size) or no data (its denominator is zero); `held` is True or False for the first two and None for the others. `failed` is
    None when no verdict can be given: the race is partial or not the registered size, or a row that decides it has no data.
    `dropped["registered"]` says what was read and why it is not the registered size. When either arm is missing or no unit is
    usable the result is ([], False, None): there is nothing to check."""
    if team_report.AGENT not in team_report.arm_names(results) or TEAM not in team_report.arm_names(results):
        return [], False, None
    clean_results, dropped = team_report.clean_units(results, drop_limits=False)
    usable = clean_results["runs"]
    if dropped["kept"] == 0:
        return [], False, None
    problems = registered_size_problems(results, dropped, usable)
    clean = {"results": clean_results, "stats": {arm: team_report.arm_stats(clean_results, arm) for arm in (AGENT, TEAM)}}
    rows = []
    for ident, claim, metric, check in PREDICTIONS:
        held, evidence = check(clean, usable)
        status = _status(held, bool(problems) and ident in ABSOLUTE_COUNT_ROWS)
        rows.append({"id": ident, "claim": claim, "metric": metric, "status": status, "evidence": evidence,
                     "held": held if status in ("held", "not held") else None})
    deciding = [row["held"] for row in rows if row["id"] in FAILS_IF]
    if problems:
        failed = None                                   # no verdict on a race that is not the registered size
    elif any(held is False for held in deciding):
        failed = True                                   # one deciding row is not held, whatever the others have
    else:
        failed = None if None in deciding else False    # all held is a pass; a deciding row with no data is no verdict
    return rows, failed, dict(dropped, registered={"units": REGISTERED_UNITS, "read": dropped["kept"], "problems": problems},
                              prediction_doc=(results.get("meta") or {}).get("prediction_doc"))


def why_not_checkable(results):
    """One sentence on why check_prediction found nothing to check, for the script to print under the standard message."""
    arms = team_report.arm_names(results)
    for arm in (team_report.AGENT, TEAM):
        if arm not in arms:
            return f"the race has no {arm} arm."
    _clean, dropped = team_report.clean_units(results, drop_limits=False)
    return (f"read on {dropped['kept']} of {dropped['units']} units: {dropped['dropped_for_provider']} dropped for a provider problem, "
            f"{dropped['incomplete']} incomplete (a unit is a task and a repeat that both arms ran).")


def format_prediction(rows, failed, dropped, label):
    """The result as printable lines."""
    if not rows:
        return [f"Cannot check the prediction on '{label}': it needs a race with both the agent and the team arm, and at least one "
                "unit (a task and a repeat) that both ran without a provider problem."]
    registered = dropped.get("registered") or {}
    problems = registered.get("problems") or []
    lines = [f"=== Week 10 prediction, checked against race '{label}' ==="]
    if dropped.get("prediction_doc"):
        lines.append(f"prediction document recorded with this race: git blob {dropped['prediction_doc']}")
    if problems:
        lines += [f"PARTIAL: read on {registered['read']} of {registered['units']} registered units ({'; '.join(problems)}).",
                  f"The thresholds were registered for {REGISTERED_TASKS} tasks x {REGISTERED_REPEATS} repeats = {REGISTERED_UNITS} units, so the rows that "
                  "count runs or tasks (P1's task count, P4, P5, P6, P9) are not decidable on this race, and no verdict is given for the prediction as a whole.", ""]
    lines += [f"read on {dropped['kept']} of {dropped['units']} units ({dropped['dropped_for_provider']} dropped for a provider problem, "
              f"{dropped['incomplete']} incomplete; units that hit a limit stay in, P9 counts them)"]
    if dropped["dropped_for_provider"]:
        lines.append("A unit dropped for a provider problem can be run again: python scripts/race_team.py --label "
                     f"{label} --model <the model the race used> --resume (with the same --only, --repeats and --timeout, if it had them).")
    lines.append("")
    words = {"held": "held", "not held": "NOT HELD", "partial": "PARTIAL", "no data": "NO DATA"}
    for row in rows:
        status = row.get("status") or {True: "held", False: "not held", None: "no data"}[row["held"]]
        lines.append(f"{row['id']:<4}{words[status]:<9}{row['claim']}")
        lines.append(f"{'':<13}{'not decidable on a partial race: ' if status == 'partial' else ''}{row['evidence']}")
    if failed is None:
        why = "the race is partial or not the registered size" if problems else "a row that decides it has no data"
        lines += ["", f"No verdict on the prediction as a whole: {why}."]
    else:
        lines += ["", f"The prediction as a whole: {'FAILED' if failed else 'did not fail'} (it fails if any of {', '.join(FAILS_IF)} does not hold)."]
    lines.append("Every analysis not listed here is exploratory. The verdict about which design to use is yours to write in findings.md.")
    return lines
