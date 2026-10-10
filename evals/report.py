"""Turn saved results into the tables the brief asks for: a score per problem type, and a
before-and-after comparison.

One overall percentage hides which kind of question got better or worse. These
functions group the cases by `problem_type` and show, for each group, how many cases ran and how
many passed. The comparison then lines two saved runs up group by group, and names the individual
cases that were fixed or broken by the change, so a gain can be traced to specific questions.

Three scores are kept apart on purpose:
  rules    the free assertion checks (cited the right document, refused or answered correctly,
           contains the facts)
  judge    the AI judge's pass rate (blank when the judge was not run)
  both     passed the rules AND the judge: the strict score. This is the headline when a judge ran.
"""


def _case_flags(case):
    """(passed the rules, judge verdict or None, passed both)."""
    judge = (case.get("judge") or {}).get("verdict")
    rules = bool(case["passed"])
    both = rules and (judge == "pass") if judge is not None else rules
    return rules, judge, both


def _blank():
    return {"n": 0, "rules": 0, "judged": 0, "judge_pass": 0, "judge_error": 0, "both": 0}


def summarize(results):
    """{"by_type": {type: counts}, "overall": counts}. Counts are numbers of cases, not percentages."""
    by_type, overall = {}, _blank()
    for case in results["cases"]:
        rules, judge, both = _case_flags(case)
        for bucket in (by_type.setdefault(case["problem_type"], _blank()), overall):
            bucket["n"] += 1
            bucket["rules"] += rules
            bucket["both"] += both
            if judge is not None:
                bucket["judged"] += 1
                bucket["judge_pass"] += judge == "pass"
                bucket["judge_error"] += judge == "error"
    return {"by_type": dict(sorted(by_type.items())), "overall": overall}


def _pct(part, whole):
    return f"{part / whole:.0%}" if whole else "-"


def headline(counts):
    """The strict score for a group: both when a judge ran, otherwise the rules alone."""
    return counts["both"] / counts["n"] if counts["n"] else 0.0


def format_summary(results):
    summary = summarize(results)
    meta = results.get("meta", {})
    lines = [f"=== eval run '{meta.get('label', '?')}' ===",
             f"answer model: {meta.get('models', {}).get('answer', '?')} · judge: "
             f"{meta.get('models', {}).get('judge') or 'not run'} · retrieval: {meta.get('settings', {}).get('retrieval_mode', '?')}"
             f" · {meta.get('chunk_count', '?')} chunks · {len(results['cases'])} cases", ""]
    lines.append(f"{'problem type':<24}{'n':>4}{'rules':>8}{'judge':>8}{'both':>8}")
    for name, counts in list(summary["by_type"].items()) + [("ALL", summary["overall"])]:
        judge_cell = _pct(counts["judge_pass"], counts["judged"])
        lines.append(f"{name:<24}{counts['n']:>4}{_pct(counts['rules'], counts['n']):>8}"
                     f"{judge_cell:>8}{_pct(counts['both'], counts['n']):>8}")
    errors = summary["overall"]["judge_error"]
    if errors:
        lines.append(f"\n{errors} judge reply(ies) could not be read and count as not passing. See the run file.")
    failing = [c for c in results["cases"] if not _case_flags(c)[2]]
    lines.append("")
    lines.append(f"cases that did not pass both: {len(failing)}")
    for case in failing:
        reasons = [check["detail"] for check in case["checks"] if not check["passed"]]
        judge = case.get("judge") or {}
        if judge.get("verdict") == "fail":
            reasons.append(f"judge: {judge.get('reason', '')}")
        lines.append(f"  - {case['id']} ({case['problem_type']}): {'; '.join(reasons) or 'judge did not pass it'}")
    for case in results["cases"]:
        for warning in case.get("warnings", []):
            lines.append(f"  ! {case['id']}: {warning}")
    return lines


def compare(before, after):
    """Line two runs up. Cases are matched by id; only cases present in BOTH are compared."""
    before_by_id = {c["id"]: c for c in before["cases"]}
    after_by_id = {c["id"]: c for c in after["cases"]}
    shared = [case_id for case_id in before_by_id if case_id in after_by_id]
    types = {}
    fixed, regressed, unchanged_fail = [], [], []
    for case_id in shared:
        old, new = before_by_id[case_id], after_by_id[case_id]
        was, now = _case_flags(old)[2], _case_flags(new)[2]
        bucket = types.setdefault(new["problem_type"], {"n": 0, "before": 0, "after": 0})
        bucket["n"] += 1
        bucket["before"] += was
        bucket["after"] += now
        if not was and now:
            fixed.append(case_id)
        elif was and not now:
            regressed.append(case_id)
        elif not was and not now:
            unchanged_fail.append(case_id)
    total = {"n": len(shared), "before": sum(b["before"] for b in types.values()),
             "after": sum(b["after"] for b in types.values())}
    return {"types": dict(sorted(types.items())), "total": total, "fixed": fixed, "regressed": regressed,
            "still_failing": unchanged_fail,
            "only_before": sorted(set(before_by_id) - set(after_by_id)),
            "only_after": sorted(set(after_by_id) - set(before_by_id))}


def format_compare(before, after):
    result = compare(before, after)
    b_label, a_label = before.get("meta", {}).get("label", "before"), after.get("meta", {}).get("label", "after")
    lines = [f"=== before '{b_label}' vs after '{a_label}' ===", ""]
    for key, run in (("before", before), ("after", after)):
        meta = run.get("meta", {})
        lines.append(f"{key:<7}: answer {meta.get('models', {}).get('answer', '?')}, judge "
                     f"{meta.get('models', {}).get('judge') or 'not run'}, {meta.get('chunk_count', '?')} chunks, "
                     f"settings {meta.get('overrides') or 'as configured'}")
    lines.append("")
    lines.append(f"{'problem type':<24}{'n':>4}{'before':>9}{'after':>9}{'change':>9}")
    for name, bucket in list(result["types"].items()) + [("ALL", result["total"])]:
        before_rate = bucket["before"] / bucket["n"] if bucket["n"] else 0
        after_rate = bucket["after"] / bucket["n"] if bucket["n"] else 0
        lines.append(f"{name:<24}{bucket['n']:>4}{before_rate:>9.0%}{after_rate:>9.0%}{(after_rate - before_rate) * 100:>+8.0f}pt")
    lines.append("")
    lines.append(f"fixed by the change    : {len(result['fixed'])}  {result['fixed']}")
    lines.append(f"BROKEN by the change   : {len(result['regressed'])}  {result['regressed']}")
    lines.append(f"still failing          : {len(result['still_failing'])}  {result['still_failing']}")
    if result["only_before"] or result["only_after"]:
        lines.append(f"not compared (in one run only): before {result['only_before']}, after {result['only_after']}")
    n = result["total"]["n"]
    lines.append("")
    lines.append(f"How much to trust this: {n} cases in total, so one case moves the overall score by "
                 f"{1 / n:.1%} and by far more inside a small group. Read the named cases above, not only the percentages." if n
                 else "No cases in common between the two runs.")
    return lines


def format_runs(runs, markdown=False):
    """One row per saved run, so a series of experiments reads as a single table.

    `runs` is a list of loaded result dicts. The counts are numbers of cases ("38/41"), not percentages,
    because with 41 cases a percentage hides how small a change is.
    """
    header = ["run", "what was changed", "chunks", "rules", "judge", "both"]
    rows = []
    for run in runs:
        meta = run.get("meta", {})
        overall = summarize(run)["overall"]
        changed = ", ".join(f"{k}={v}" for k, v in (meta.get("overrides") or {}).items()) or "nothing (the baseline settings)"
        judged = f"{overall['judge_pass']}/{overall['judged']}" if overall["judged"] else "not run"
        rows.append([meta.get("label", "?"), changed, str(meta.get("chunk_count", "?")),
                     f"{overall['rules']}/{overall['n']}", judged, f"{overall['both']}/{overall['n']}"])
    if markdown:
        lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        return lines + ["| " + " | ".join(row) + " |" for row in rows]
    widths = [max(len(str(cell)) for cell in column) for column in zip(header, *rows)]
    return ["  ".join(str(cell).ljust(width) for cell, width in zip(line, widths)) for line in [header] + rows]
