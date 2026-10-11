"""Check the pre-registered prediction for the per-tool call budget against saved runs (Week 8).

Before the fix was measured, `docs/week8/CHANGES.md` wrote down what the fix should do and what
would count as it failing. This turns those sentences into arithmetic over the saved "before" and "after" runs, so
nobody has to decide afterwards whether the prediction held. The thresholds below are copied from that section and
must change only if that section does (and that section is committed before any "after" run exists).

The predictions, on the (task, repeat) pairs both runs completed:
  1. `over-calling` goes to 0 (true by construction: the grader's threshold is four calls that returned a result, the
     cap is three, and `remember`, which the cap does not limit, is not counted)
  2. the number of right answers falls by at most 2
  3. mean tokens per run: REPORTED next to a noise floor, not judged (see the amendment: the first version of this
     prediction gave a 2% to 8% window, which is smaller than the difference between two identical runs)
  4. at most 2 runs that finished before now end without an answer
  5. `unverified-citation` is unchanged
The fix has FAILED if the right answers fall by more than 2, or more than 2 finished runs now end without an answer.

The noise floor is how much two IDENTICAL runs (no cap, same model, same day) differ in mean tokens per run. A change
smaller than that cannot be told from chance, so it is reported as "not distinguishable from noise". The effect and the
noise are read on the SAME pairs: the (task, repeat) pairs all three runs completed. A pair in which either run ended on a
provider error is left out of everything (an outage is not evidence about the cap), and the number left out is printed.
"""
import json

from evals import trajectory

MAX_FEWER_RIGHT = 2
MAX_NEW_UNFINISHED = 2


def _finished(record):
    return record.get("stop_reason") == "final"


def _key(record):
    return (record["task_id"], record.get("repeat"))


def _mean_fall(before, after, key):
    """(mean before, mean after, fall as a fraction of the mean before) for one cost measure."""
    mean_before = trajectory.cost_summary(before)[key]["mean"]
    mean_after = trajectory.cost_summary(after)[key]["mean"]
    return mean_before, mean_after, ((mean_before - mean_after) / mean_before if mean_before else 0.0)


def _versus_noise(fall, noise, pairs):
    if noise is None:
        return "no A/A run given, or no pair that all three runs completed, so the noise floor is unknown"
    verdict = "larger than the noise floor" if abs(fall) > noise else "not distinguishable from noise"
    return f"{verdict} (two identical runs differ by {noise:.1%}; read on the {pairs} pair(s) all three runs completed)"


def check_setup(before_meta, after_meta, noise_meta=None):
    """Warnings when the runs do not differ only in the call cap: another model, the cap not recorded or equal, a run
    cut short, defences on in one. An empty list means nothing was found wrong; a missing field is said, not guessed."""
    runs = [("before", before_meta), ("after", after_meta)] + ([("noise", noise_meta)] if noise_meta is not None else [])
    warnings = []
    models = {name: (meta.get("models") or {}).get("agent") for name, meta in runs}
    if len(set(models.values())) > 1:
        warnings.append(f"the runs used different models: {models}")
    caps = {name: meta.get("agent_max_calls_per_tool") for name, meta in runs}
    if any(cap is None for cap in caps.values()):
        warnings.append("the call cap in force was not recorded for every run (older files), so it cannot be checked")
    else:
        if caps["before"] != 0 or caps.get("noise", 0) != 0:
            warnings.append(f"'before' and the noise run should have no cap, but the caps were {caps}")
        if caps["after"] == caps["before"]:
            warnings.append(f"'after' has the same call cap as 'before' ({caps['after']}), so it tests nothing")
    for field in ("retrieval_mode", "limits", "tasks", "top_k_workflow"):
        values = {name: meta.get(field) for name, meta in runs if field in meta}
        if len({json.dumps(value, sort_keys=True, default=str) for value in values.values()}) > 1:
            warnings.append(f"the runs differ in {field}: {values}")
    others = {name: {key: value for key, value in (meta.get("overrides") or {}).items() if key != "agent_max_calls_per_tool"}
              for name, meta in runs}
    if len({json.dumps(value, sort_keys=True, default=str) for value in others.values()}) > 1:
        warnings.append(f"the runs changed other settings differently: {others}")
    for name, meta in runs:
        if meta.get("defense"):
            warnings.append(f"the '{name}' run had the defences on")
        if not meta.get("complete", True):
            warnings.append(f"the '{name}' run is partial ({meta.get('stopped_because') or 'no reason recorded'}): only pairs it completed are used")
    return warnings


def check_budget_prediction(before_records, after_records, tasks, noise_records=None):
    """Rows of {number, claim, measured, held} for the predictions, plus whether the fix failed, and the pair count.

    `held` is True or False for a prediction that is judged, and None for a figure that is only reported.
    noise_records: a second run of the same configuration as `before_records` (the A/A run), or None.
    """
    known = {task["id"] for task in tasks}
    before_all = [r for r in before_records if r["task_id"] in known]
    before, after = trajectory.pair_records(before_all, [r for r in after_records if r["task_id"] in known])
    usable = [(x, y) for x, y in zip(before, after) if x.get("stop_reason") != "error" and y.get("stop_reason") != "error"]
    left_out = len(before) - len(usable)
    before, after = [x for x, _ in usable], [y for _, y in usable]
    if not before:
        return [], False, 0
    left_note = f" ({left_out} pair(s) left out: a run ended on a provider error)" if left_out else ""
    b = trajectory.summarize(trajectory.grade_all(before, tasks), before)
    a = trajectory.summarize(trajectory.grade_all(after, tasks), after)
    over_before, over_after = b["modes"].get("over-calling", 0), a["modes"].get("over-calling", 0)
    right_drop = b["outcome_ok"] - a["outcome_ok"]
    new_unfinished = sum(1 for x, y in zip(before, after) if _finished(x) and not _finished(y))
    cite_before, cite_after = b["modes"].get("unverified-citation", 0), a["modes"].get("unverified-citation", 0)

    # cost: the effect and the noise are read on the SAME pairs, those all three runs completed
    if noise_records is None:
        cost_before, cost_after, cost_noise = before, after, None
    else:
        noise_all = [r for r in noise_records if r["task_id"] in known]
        keys = {_key(r) for r in before} & {_key(r) for r in noise_all}
        cost_before, cost_after = [r for r in before if _key(r) in keys], [r for r in after if _key(r) in keys]
        cost_noise = [r for r in noise_all if _key(r) in keys]

    def cost_row(number, claim, key, fmt):
        if not cost_before:
            return {"number": number, "claim": claim, "measured": "no pair that all three runs completed", "held": None}
        mean_before, mean_after, fall = _mean_fall(cost_before, cost_after, key)
        noise = abs(_mean_fall(cost_before, cost_noise, key)[2]) if cost_noise else None
        return {"number": number, "claim": claim,
                "measured": f"{fmt(mean_before)} before, {fmt(mean_after)} after ({fall:+.1%} fall): {_versus_noise(fall, noise, len(cost_before))}",
                "held": None}

    rows = [
        {"number": 1, "claim": "over-calling goes to 0", "measured": f"{over_before} runs before, {over_after} after",
         "held": over_after == 0},
        {"number": 2, "claim": f"right answers fall by at most {MAX_FEWER_RIGHT}",
         "measured": f"{b['outcome_ok']} before, {a['outcome_ok']} after (fell by {right_drop}){left_note}", "held": right_drop <= MAX_FEWER_RIGHT},
        cost_row(3, "mean tokens per run (reported, not judged)", "tokens", lambda value: f"{value:.0f}"),
        {"number": 4, "claim": f"at most {MAX_NEW_UNFINISHED} finished runs now end without an answer",
         "measured": f"{new_unfinished} run(s){left_note}", "held": new_unfinished <= MAX_NEW_UNFINISHED},
        {"number": 5, "claim": "unverified-citation is unchanged",
         "measured": f"{cite_before} before, {cite_after} after", "held": cite_before == cite_after},
        cost_row(6, "mean model calls per run (reported, not judged)", "calls", lambda value: f"{value:.1f}"),
    ]
    failed = right_drop > MAX_FEWER_RIGHT or new_unfinished > MAX_NEW_UNFINISHED
    return rows, failed, len(before)


def format_prediction(rows, failed, pairs, label_before="before", label_after="after", warnings=()):
    if not rows:
        return ["The two runs have no (task, repeat) in common, so the prediction cannot be checked."]
    lines = [f"Pre-registered prediction for the call budget, checked on the {pairs} (task, repeat) pairs "
             f"both '{label_before}' and '{label_after}' completed:", ""]
    if warnings:
        lines += ["SETUP WARNINGS (the runs may not differ only in the call cap):"] + [f"  - {text}" for text in warnings] + [""]
    for row in rows:
        status = "REPORTED, NOT JUDGED" if row["held"] is None else ("HELD" if row["held"] else "DID NOT HOLD")
        lines.append(f"  {row['number']}. {row['claim']}")
        lines.append(f"       {row['measured']}   [{status}]")
    lines += ["", "The fix has failed if the right answers fall by more than 2, or more than 2 finished runs now end without an "
              "answer. (The token condition in the first version was withdrawn before the measured runs: see the amendment in CHANGES.md.)",
              "Verdict on that rule: " + ("THE FIX FAILED." if failed else "the fix did not fail."),
              f"A difference of one or two runs is within what a second identical run could change (n = {pairs}), and one A/A pair is "
              "one sample of the noise, not its distribution: a change of the size of the noise would read as larger than it in "
              "roughly half of all pairs of identical runs."]
    return lines
