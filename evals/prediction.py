"""Check the pre-registered prediction for the per-tool call budget against two saved runs (Week 8).

Before the fix was measured, `docs/week8/CHANGES.md` wrote down what the fix should do and what
would count as it failing. This turns those sentences into arithmetic over the saved "before" and "after" runs, so
nobody has to decide afterwards whether the prediction held. The thresholds below are copied from that section and
must change only if that section does (and that section is committed before any "after" run exists).

The predictions, on the (task, repeat) pairs both runs completed:
  1. `over-calling` goes to 0 (true by construction: it is the grader's own threshold of four calls, the cap is three)
  2. the number of right answers falls by at most 2
  3. mean tokens per run fall by 2% to 8% (the ceiling on what a cap can save is higher, so more is not a failure)
  4. at most 2 runs that finished before now end without an answer
  5. `unverified-citation` is unchanged
The fix has FAILED if the right answers fall by more than 2, or more than 2 finished runs now end without an answer,
or mean tokens fall by less than 2%.
"""
from evals import trajectory

MAX_FEWER_RIGHT = 2
TOKEN_FALL_RANGE = (0.02, 0.08)
MAX_NEW_UNFINISHED = 2


def _finished(record):
    return record.get("stop_reason") == "final"


def check_budget_prediction(before_records, after_records, tasks):
    """Rows of {number, claim, measured, held} for the five predictions, plus whether the fix failed, and the pair count."""
    known = {task["id"] for task in tasks}
    before, after = trajectory.pair_records([r for r in before_records if r["task_id"] in known],
                                            [r for r in after_records if r["task_id"] in known])
    if not before:
        return [], False, 0
    b = trajectory.summarize(trajectory.grade_all(before, tasks), before)
    a = trajectory.summarize(trajectory.grade_all(after, tasks), after)
    over_before, over_after = b["modes"].get("over-calling", 0), a["modes"].get("over-calling", 0)
    right_drop = b["outcome_ok"] - a["outcome_ok"]
    before_tokens, after_tokens = b["cost"]["tokens"]["mean"], a["cost"]["tokens"]["mean"]
    fall = (before_tokens - after_tokens) / before_tokens if before_tokens else 0.0
    new_unfinished = sum(1 for x, y in zip(before, after) if _finished(x) and not _finished(y))
    cite_before, cite_after = b["modes"].get("unverified-citation", 0), a["modes"].get("unverified-citation", 0)

    low, high = TOKEN_FALL_RANGE
    rows = [
        {"number": 1, "claim": "over-calling goes to 0", "measured": f"{over_before} runs before, {over_after} after",
         "held": over_after == 0},
        {"number": 2, "claim": f"right answers fall by at most {MAX_FEWER_RIGHT}",
         "measured": f"{b['outcome_ok']} before, {a['outcome_ok']} after (fell by {right_drop})", "held": right_drop <= MAX_FEWER_RIGHT},
        {"number": 3, "claim": f"mean tokens per run fall by {low:.0%} to {high:.0%}",
         "measured": f"{before_tokens:.0f} before, {after_tokens:.0f} after ({fall:+.1%} fall)", "held": low <= fall <= high},
        {"number": 4, "claim": f"at most {MAX_NEW_UNFINISHED} finished runs now end without an answer",
         "measured": f"{new_unfinished} run(s)", "held": new_unfinished <= MAX_NEW_UNFINISHED},
        {"number": 5, "claim": "unverified-citation is unchanged",
         "measured": f"{cite_before} before, {cite_after} after", "held": cite_before == cite_after},
    ]
    failed = right_drop > MAX_FEWER_RIGHT or new_unfinished > MAX_NEW_UNFINISHED or fall < low
    return rows, failed, len(before)


def format_prediction(rows, failed, pairs, label_before="before", label_after="after"):
    if not rows:
        return ["The two runs have no (task, repeat) in common, so the prediction cannot be checked."]
    lines = [f"Pre-registered prediction for the call budget, checked on the {pairs} (task, repeat) pairs "
             f"both '{label_before}' and '{label_after}' completed:", ""]
    for row in rows:
        lines.append(f"  {row['number']}. {row['claim']:<52} {row['measured']:<48} {'HELD' if row['held'] else 'DID NOT HOLD'}")
    lines += ["", "The fix has failed if the right answers fall by more than 2, or more than 2 finished runs now end without an "
              "answer, or mean tokens fall by less than 2%.",
              "Verdict on that rule: " + ("THE FIX FAILED." if failed else "the fix did not fail."),
              f"A difference of one or two runs is within what a second identical run could change (n = {pairs})."]
    return lines
