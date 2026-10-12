"""Check the pre-registered prediction for the cost measurement against a saved measurement (Week 11).

Before any request was sent to the model, `docs/week11/prediction.md` wrote down how much cheaper the one
improvement (CONTEXT_STRIP_MIN_REPEATS=10) should make a request and what would count as the prediction failing. This turns those
sentences into arithmetic over the saved measurement (scripts/measure_cost.py), so nobody has to decide afterwards whether it held.
The numbers below are copied from that document and change only if it does, and it was committed before the first live request.

Whether the improvement ships is your decision and no check here makes it. Every prediction is about a MEASURED quantity.

Where the bands come from. The free screen (scripts/estimate_context_savings.py, no model calls) says the strip removes 17.9% of the
prompt's characters on the 41 eval questions and 27.2% on 30 questions drawn from the Week 5 bank with seed 42 (retrieval dense,
top_k 4, 432 chunks). Tokens are not characters: the removed lines tokenize about like the rest of the prompt, so the share of
tokens removed is taken as the share of characters times a factor between 0.65 and 1.3, which gives a ratio of mean prompt tokens
after to before of 0.77 to 0.88 on the eval questions and 0.65 to 0.82 on the bank, widened a little to 0.75 to 0.90 and 0.62 to
0.85. The model's replies are written from the same facts, so their length should not move beyond sampling noise.

The predictions, read on the questions every arm answered with the provider's own token counts:
  P1  prompt tokens, eval questions: the mean after / before is between 0.75 and 0.90
  P2  prompt tokens, bank questions (read only when at least 20 were asked): between 0.62 and 0.85
  P3  noise floor: `before` and `before-2` send the same prompt tokens on at least 95% of the questions, and their means differ by
      less than 1%
  P4  completion tokens: the mean after / before is between 0.85 and 1.15
  P5  quality: no eval question that passes its rule checks under `before` fails them under `after`, except a question whose
      result also differs between `before` and `before-2` (that one is noise, not the idea)
  P6  sources: on the three conflict questions (ambiguous-leave-days, ambiguous-notice-period, ambiguous-learning-budget) every
      document cited under `before` is still cited under `after`
  P7  reach: the strip removed at least one character on at least 60% of the eval requests
The prediction has FAILED if P1, P5 or P6 does not hold; P5 and P6 are the stop rule: the setting stays off and the trade-off is
reported. The others are reported held or not held, with no verdict on the whole. Every analysis not listed here is exploratory.
A dry run, a run that stopped early and a run that did not ask the registered questions get no verdict at all.
"""
from evals import cost_run

BEFORE, AFTER, NOISE = "before", "after", "before-2"
REGISTERED_ARMS = (BEFORE, AFTER, NOISE)
REGISTERED_EVAL_QUESTIONS = 41
MIN_BANK_QUESTIONS = 20
TOKEN_BANDS = {"eval": (0.75, 0.90), "bank": (0.62, 0.85)}
SAME_PROMPT_SHARE, NOISE_MEAN_DIFFERENCE = 0.95, 0.01
COMPLETION_BAND = (0.85, 1.15)
CONFLICT_QUESTIONS = ("ambiguous-leave-days", "ambiguous-notice-period", "ambiguous-learning-budget")
REACH_SHARE = 0.60
FAILS_IF = ("P1", "P5", "P6")


def _row(item_id, held, evidence, decidable=True):
    return {"id": item_id, "held": held if decidable else None, "decidable": decidable, "evidence": evidence}


def _by_question(rows, kind):
    """{question id: {arm: row}} for the rows of one kind that answered with the provider's own token counts."""
    table = {}
    for row in rows:
        if row["kind"] == kind and row["status"] != "error" and row["tokens_known"] and row["prompt_tokens"] is not None:
            table.setdefault(row["question_id"], {})[row["arm"]] = row
    return table


def _complete_questions(rows, kind):
    """The questions every registered arm answered, so each arm's mean is over the same questions."""
    return {question: arms for question, arms in _by_question(rows, kind).items() if all(arm in arms for arm in REGISTERED_ARMS)}


def _mean(values):
    values = list(values)
    return sum(values) / len(values) if values else None


def _ratio(numerator, denominator):
    return None if not denominator or numerator is None else numerator / denominator


def _token_ratio(rows, kind, key="prompt_tokens"):
    complete = _complete_questions(rows, kind)
    before = _mean(arms[BEFORE][key] for arms in complete.values())
    after = _mean(arms[AFTER][key] for arms in complete.values())
    return _ratio(after, before), len(complete), before, after


def check_prediction(results):
    """The result of every prediction on a saved measurement: {"cannot_check": reason or None, "rows": [...], "verdict": ...}.
    The verdict is "FAILED", "did not fail" or None when the measurement cannot carry one (and then a reason says why)."""
    meta, rows = results["meta"], results["rows"]
    arms = [arm["name"] for arm in meta.get("arms", [])]
    if meta.get("dry_run"):
        return {"cannot_check": "this is a dry run: its tokens come from a scripted provider and are not measurements", "rows": [], "verdict": None}
    if tuple(arms) != REGISTERED_ARMS:
        return {"cannot_check": f"the registered arms are {list(REGISTERED_ARMS)} in that order, this measurement has {arms}", "rows": [], "verdict": None}
    if (meta.get("settings") or {}).get("context_strip_min_repeats"):
        return {"cannot_check": "the strip was already on in the settings the measurement started from, so `before` stripped too and nothing was compared", "rows": [], "verdict": None}
    overrides = {arm["name"]: arm["overrides"] for arm in meta["arms"]}
    if overrides[BEFORE] or overrides[NOISE] or overrides[AFTER] != {"context_strip_min_repeats": 10}:
        return {"cannot_check": f"the registered arms change nothing, and the strip at 10; this measurement has {overrides}", "rows": [], "verdict": None}

    partial = []
    if not meta.get("complete"):
        partial.append(f"the measurement stopped early ({meta.get('stopped_because')})")
    if meta.get("n_eval") != REGISTERED_EVAL_QUESTIONS:
        partial.append(f"it asked {meta.get('n_eval')} eval questions, the prediction is registered for {REGISTERED_EVAL_QUESTIONS}")
    if len(_complete_questions(rows, "eval")) != REGISTERED_EVAL_QUESTIONS:
        partial.append(f"only {len(_complete_questions(rows, 'eval'))} of {REGISTERED_EVAL_QUESTIONS} eval questions were answered by every arm with token counts")

    out = [_p1(rows), _p2(rows, meta), _p3(rows), _p4(rows), _p5(rows), _p6(rows), _p7(rows)]
    if partial:
        for row in out:
            row.update(held=None, decidable=False, evidence=row["evidence"] + " (not decidable: the measurement is partial)")
        return {"cannot_check": None, "partial": partial, "rows": out, "verdict": None}
    undecided = [row["id"] for row in out if row["id"] in FAILS_IF and not row["decidable"]]
    if undecided:                                     # a prediction that could not be read is not a prediction that failed
        return {"cannot_check": None, "partial": [f"{', '.join(undecided)} could not be decided from this measurement"], "rows": out, "verdict": None}
    failed = [row["id"] for row in out if row["id"] in FAILS_IF and row["held"] is not True]
    return {"cannot_check": None, "partial": [], "rows": out, "verdict": "FAILED" if failed else "did not fail", "failed": failed}


def _p1(rows):
    ratio, n, before, after = _token_ratio(rows, "eval")
    low, high = TOKEN_BANDS["eval"]
    if ratio is None:
        return _row("P1", None, "no eval question was answered by every arm with token counts", decidable=False)
    return _row("P1", low <= round(ratio, 2) <= high, f"mean prompt tokens {before:.1f} before, {after:.1f} after: ratio {ratio:.2f} on {n} questions, band {low} to {high}")


def _p2(rows, meta):
    low, high = TOKEN_BANDS["bank"]
    if (meta.get("n_bank") or 0) < MIN_BANK_QUESTIONS:
        return _row("P2", None, f"only {meta.get('n_bank') or 0} bank questions were asked, at least {MIN_BANK_QUESTIONS} are needed", decidable=False)
    ratio, n, before, after = _token_ratio(rows, "bank")
    if ratio is None:
        return _row("P2", None, "no bank question was answered by every arm with token counts", decidable=False)
    return _row("P2", low <= round(ratio, 2) <= high, f"mean prompt tokens {before:.1f} before, {after:.1f} after: ratio {ratio:.2f} on {n} questions, band {low} to {high}")


def _p3(rows):
    complete = list(_complete_questions(rows, "eval").values()) + list(_complete_questions(rows, "bank").values())
    if not complete:
        return _row("P3", None, "no question was answered by both noise arms with token counts", decidable=False)
    same = sum(1 for arms in complete if arms[BEFORE]["prompt_tokens"] == arms[NOISE]["prompt_tokens"])
    mean_before, mean_noise = _mean(a[BEFORE]["prompt_tokens"] for a in complete), _mean(a[NOISE]["prompt_tokens"] for a in complete)
    difference = abs(mean_noise - mean_before) / mean_before if mean_before else None
    held = same / len(complete) >= SAME_PROMPT_SHARE and difference is not None and difference < NOISE_MEAN_DIFFERENCE
    return _row("P3", held, f"the same prompt tokens on {same} of {len(complete)} questions ({same / len(complete):.0%}, need {SAME_PROMPT_SHARE:.0%}); "
                            f"the means differ by {difference:.2%} (need under {NOISE_MEAN_DIFFERENCE:.0%})")


def _p4(rows):
    ratio, n, before, after = _token_ratio(rows, "eval", "completion_tokens")
    low, high = COMPLETION_BAND
    if ratio is None:
        return _row("P4", None, "no eval question was answered by every arm with token counts", decidable=False)
    return _row("P4", low <= round(ratio, 2) <= high, f"mean completion tokens {before:.1f} before, {after:.1f} after: ratio {ratio:.2f} on {n} questions, band {low} to {high}")


def _p5(rows):
    moved = cost_run.flips(rows, BEFORE, AFTER)
    noise = cost_run.flips(rows, BEFORE, NOISE)
    flaky = set(noise["pass_to_fail"])                # passed under before, failed under before-2: the same arm twice differs, so it is noise
    real = [question for question in moved["pass_to_fail"] if question not in flaky]
    note = f"; set aside as noise (also differs between before and before-2): {sorted(set(moved['pass_to_fail']) & flaky)}" if set(moved["pass_to_fail"]) & flaky else ""
    return _row("P5", not real, f"{len(real)} eval questions went from passing to failing under after: {real or 'none'}, on {moved['compared']} compared{note}")


def _p6(rows):
    cited = {}
    for row in rows:
        if row["question_id"] in CONFLICT_QUESTIONS and row["status"] != "error":
            cited.setdefault(row["question_id"], {})[row["arm"]] = set(row["sources"])
    complete = {question: arms for question, arms in cited.items() if BEFORE in arms and AFTER in arms}
    if len(complete) < len(CONFLICT_QUESTIONS):
        return _row("P6", None, f"only {len(complete)} of the {len(CONFLICT_QUESTIONS)} conflict questions were answered by both arms", decidable=False)
    lost = {question: sorted(arms[BEFORE] - arms[AFTER]) for question, arms in complete.items() if arms[BEFORE] - arms[AFTER]}
    return _row("P6", not lost, f"documents cited before and no longer after: {lost or 'none'}")


def _p7(rows):
    stripped = [row for row in rows if row["arm"] == AFTER and row["kind"] == "eval" and row["status"] != "error"]
    if not stripped:
        return _row("P7", None, "no eval request under after", decidable=False)
    reached = sum(1 for row in stripped if (row["chars"] or {}).get("stripped", 0) > 0)
    return _row("P7", reached / len(stripped) >= REACH_SHARE, f"the strip removed something on {reached} of {len(stripped)} eval requests ({reached / len(stripped):.0%}, need {REACH_SHARE:.0%})")


def format_prediction(check):
    """Printable lines for check_prediction's result."""
    if check["cannot_check"]:
        return [f"cannot check the prediction: {check['cannot_check']}"]
    lines = []
    if check.get("partial"):
        lines += ["PARTIAL: no verdict can be given on this measurement:"] + [f"  - {reason}" for reason in check["partial"]] + [""]
    for row in check["rows"]:
        mark = "held" if row["held"] else ("not held" if row["held"] is False else "not decidable")
        lines.append(f"{row['id']}  {mark:<14}{row['evidence']}")
    lines.append("")
    if check["verdict"] is None:
        lines.append("The prediction as a whole: no verdict (partial measurement).")
    elif check["verdict"] == "FAILED":
        lines.append(f"The prediction as a whole: FAILED ({', '.join(check['failed'])} did not hold). Stop rule: if P5 or P6 failed the setting stays off and the trade-off is reported.")
    else:
        lines.append("The prediction as a whole: did not fail (P1, P5 and P6 held). Whether the improvement ships is your decision.")
    return lines
