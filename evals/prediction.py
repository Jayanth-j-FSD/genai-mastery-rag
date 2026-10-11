"""Check the pre-registered prediction for the per-tool call budget against saved runs (Week 8).

Before the fix was measured, `docs/week8/CHANGES.md` wrote down what the fix should do and what
would count as it failing. This turns those sentences into arithmetic over the saved "before" and "after" runs, so
nobody has to decide afterwards whether the prediction held. The thresholds below are copied from that section and
must change only if that section does (and that section is committed before any "after" run exists).

The predictions, on the (task, repeat) pairs both runs completed:
  1. `over-calling` goes to 0 (true by construction: it is the grader's own threshold of four calls, the cap is three,
     and `remember`, which the cap does not limit, is not counted)
  2. the number of right answers falls by at most 2
  3. mean tokens per run: REPORTED next to a noise floor, not judged (see the amendment: the first version of this
     prediction gave a 2% to 8% window, which is smaller than the difference between two identical runs)
  4. at most 2 runs that finished before now end without an answer
  5. `unverified-citation` is unchanged
The fix has FAILED if the right answers fall by more than 2, or more than 2 finished runs now end without an answer.

The noise floor is how much two IDENTICAL runs (no cap, same model, same day) differ in mean tokens per run. A change
smaller than that cannot be told from chance, so it is reported as "not distinguishable from noise".
"""
from evals import trajectory

MAX_FEWER_RIGHT = 2
MAX_NEW_UNFINISHED = 2
COSTS = (("tokens", "mean tokens per run"), ("calls", "mean model calls per run"))


def _finished(record):
    return record.get("stop_reason") == "final"


def _mean_fall(before, after, key):
    """(mean before, mean after, fall as a fraction of the mean before) for one cost measure."""
    mean_before = trajectory.cost_summary(before)[key]["mean"]
    mean_after = trajectory.cost_summary(after)[key]["mean"]
    return mean_before, mean_after, ((mean_before - mean_after) / mean_before if mean_before else 0.0)


def _noise(before_records, noise_records, key):
    """How much two identical runs differ on a cost measure, as a fraction (None: no A/A run, or nothing in common)."""
    if noise_records is None:
        return None
    first, second = trajectory.pair_records(before_records, noise_records)
    return abs(_mean_fall(first, second, key)[2]) if first else None


def _versus_noise(fall, noise):
    if noise is None:
        return "no A/A run given, so the noise floor is unknown"
    verdict = "larger than the noise floor" if abs(fall) > noise else "not distinguishable from noise"
    return f"{verdict} (two identical runs differ by {noise:.1%})"


def check_budget_prediction(before_records, after_records, tasks, noise_records=None):
    """Rows of {number, claim, measured, held} for the predictions, plus whether the fix failed, and the pair count.

    `held` is True or False for a prediction that is judged, and None for a figure that is only reported.
    noise_records: a second run of the same configuration as `before_records` (the A/A run), or None.
    """
    known = {task["id"] for task in tasks}
    before_all = [r for r in before_records if r["task_id"] in known]
    before, after = trajectory.pair_records(before_all, [r for r in after_records if r["task_id"] in known])
    if not before:
        return [], False, 0
    noise_all = None if noise_records is None else [r for r in noise_records if r["task_id"] in known]
    b = trajectory.summarize(trajectory.grade_all(before, tasks), before)
    a = trajectory.summarize(trajectory.grade_all(after, tasks), after)
    over_before, over_after = b["modes"].get("over-calling", 0), a["modes"].get("over-calling", 0)
    right_drop = b["outcome_ok"] - a["outcome_ok"]
    new_unfinished = sum(1 for x, y in zip(before, after) if _finished(x) and not _finished(y))
    cite_before, cite_after = b["modes"].get("unverified-citation", 0), a["modes"].get("unverified-citation", 0)

    rows = [
        {"number": 1, "claim": "over-calling goes to 0", "measured": f"{over_before} runs before, {over_after} after",
         "held": over_after == 0},
        {"number": 2, "claim": f"right answers fall by at most {MAX_FEWER_RIGHT}",
         "measured": f"{b['outcome_ok']} before, {a['outcome_ok']} after (fell by {right_drop})", "held": right_drop <= MAX_FEWER_RIGHT},
    ]
    mean_before, mean_after, fall = _mean_fall(before, after, "tokens")
    rows.append({"number": 3, "claim": "mean tokens per run (reported, not judged)",
                 "measured": f"{mean_before:.0f} before, {mean_after:.0f} after ({fall:+.1%} fall): "
                             f"{_versus_noise(fall, _noise(before_all, noise_all, 'tokens'))}", "held": None})
    rows += [
        {"number": 4, "claim": f"at most {MAX_NEW_UNFINISHED} finished runs now end without an answer",
         "measured": f"{new_unfinished} run(s)", "held": new_unfinished <= MAX_NEW_UNFINISHED},
        {"number": 5, "claim": "unverified-citation is unchanged",
         "measured": f"{cite_before} before, {cite_after} after", "held": cite_before == cite_after},
    ]
    mean_before, mean_after, fall = _mean_fall(before, after, "calls")
    rows.append({"number": 6, "claim": "mean model calls per run (reported, not judged)",
                 "measured": f"{mean_before:.1f} before, {mean_after:.1f} after ({fall:+.1%} fall): "
                             f"{_versus_noise(fall, _noise(before_all, noise_all, 'calls'))}", "held": None})
    failed = right_drop > MAX_FEWER_RIGHT or new_unfinished > MAX_NEW_UNFINISHED
    return rows, failed, len(before)


def format_prediction(rows, failed, pairs, label_before="before", label_after="after"):
    if not rows:
        return ["The two runs have no (task, repeat) in common, so the prediction cannot be checked."]
    lines = [f"Pre-registered prediction for the call budget, checked on the {pairs} (task, repeat) pairs "
             f"both '{label_before}' and '{label_after}' completed:", ""]
    for row in rows:
        status = "REPORTED, NOT JUDGED" if row["held"] is None else ("HELD" if row["held"] else "DID NOT HOLD")
        lines.append(f"  {row['number']}. {row['claim']}")
        lines.append(f"       {row['measured']}   [{status}]")
    lines += ["", "The fix has failed if the right answers fall by more than 2, or more than 2 finished runs now end without an "
              "answer. (The token condition in the first version was withdrawn before the measured runs: see the amendment in CHANGES.md.)",
              "Verdict on that rule: " + ("THE FIX FAILED." if failed else "the fix did not fail."),
              f"A difference of one or two runs is within what a second identical run could change (n = {pairs}), and one A/A pair is "
              "one sample of the noise, not its distribution."]
    return lines
