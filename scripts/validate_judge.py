"""Week 6, mentor check #3, step 2: does the judge agree with YOUR grading?

This refuses to run until every answer in the sheet has your verdict. Then it lines
your verdicts up against the judge's hidden ones and reports how often you agree, corrected for
chance (Cohen's kappa), which way the judge errs when it disagrees, and every disagreement so you can
decide whether the judge or you were wrong. The result is a number you can defend, not a feeling.

Run:
    python scripts/validate_judge.py
    python scripts/validate_judge.py --save      # also write docs/week6/judge-validation-output.md

The bars (80% agreement and kappa 0.6 by default) are conventions, not laws. Say which you used.
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import BASE_DIR                              # noqa: E402
from app.console import display_path, make_output_safe       # noqa: E402
from evals import agreement, validation                      # noqa: E402

MINIMUM_RECOMMENDED = 20


def _snippet(text, limit=140):
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "..."


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare the judge with your own grading.")
    parser.add_argument("--in", dest="sheet", default=validation.SHEET_PATH, help="the graded sheet")
    parser.add_argument("--items", default=None, help="the hidden judge verdicts (default: items.json beside the sheet)")
    parser.add_argument("--min-agreement", type=float, default=agreement.DEFAULT_MIN_AGREEMENT)
    parser.add_argument("--min-kappa", type=float, default=agreement.DEFAULT_MIN_KAPPA)
    parser.add_argument("--save", action="store_true", help="also write docs/week6/judge-validation-output.md")
    args = parser.parse_args(argv)
    make_output_safe()
    items_path = args.items or os.path.join(os.path.dirname(args.sheet), "items.json")

    try:
        rows, problems = validation.join_labels(args.sheet, items_path)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        print("Make a sheet first:  python scripts/make_judge_sheet.py --runs baseline")
        return 1
    if problems:
        print(f"The grading is not finished: {len(problems)} thing(s) to fix in {display_path(args.sheet, BASE_DIR)}:\n")
        for problem in problems:
            print(f"  - {problem}")
        print("\nThis is deliberate. Agreement computed on a half-graded sheet would be a number about nothing.")
        return 1

    usable = [row for row in rows if row["judge_verdict"] in ("pass", "fail")]
    if not usable:
        print("None of the graded answers has a readable judge verdict, so there is nothing to compare. "
              "Re-run the evals with the judge and make a new sheet.")
        return 1
    stats = agreement.agreement_stats([(row["human"], row["judge_verdict"]) for row in usable])
    lines = []

    def emit(text=""):
        print(text)
        lines.append(text)

    emit("=== Judge validation ===")
    models = sorted({row["judge_model"] for row in usable})
    emit(f"judge model: {', '.join(models) or '?'} · graded by hand: {len(rows)} · compared: {stats['n']}")
    if stats["n"] < MINIMUM_RECOMMENDED:
        emit(f"Only {stats['n']} answers: treat the result as a rough check (at least {MINIMUM_RECOMMENDED} is recommended).")
    emit("")
    emit(f"agreement            : {stats['percent']:.0%}  ({stats['both_pass'] + stats['both_fail']} of {stats['n']})")
    kappa = stats["kappa"]
    emit(f"Cohen's kappa        : {'undefined' if kappa is None else f'{kappa:.2f}'}  ({agreement.kappa_label(kappa)})")
    emit(f"you passed / judge passed : {stats['human_pass_rate']:.0%} / {stats['judge_pass_rate']:.0%}")
    emit(f"both pass {stats['both_pass']} · both fail {stats['both_fail']} · judge too harsh {stats['judge_harsh']} "
         f"(you passed it, the judge failed it) · judge too lenient {stats['judge_lenient']} "
         f"(you failed it, the judge passed it)")
    emit("")
    trusted = agreement.is_trustworthy(stats, args.min_agreement, args.min_kappa)
    emit(f"bars used: agreement >= {args.min_agreement:.0%} and kappa >= {args.min_kappa:.2f}")
    if kappa is None:
        emit("VERDICT: cannot be judged. Every verdict was identical, so there is nothing for kappa to measure. "
             "Grade a sheet that contains both good and bad answers.")
    else:
        emit(f"VERDICT: {'the judge clears both bars; its numbers can be used, with this validation quoted next to them' if trusted else 'NOT yet trustworthy: do not quote its scores as evidence until it is improved and re-validated'}")
    emit("")

    disagreements = [row for row in usable if row["human"] != row["judge_verdict"]]
    emit(f"--- the {len(disagreements)} disagreement(s): read each and decide who was right ---")
    for row in disagreements:
        emit(f"  {row['id']} [{row['case_id']}] you: {row['human']}, judge: {row['judge_verdict']}")
        emit(f"      Q: {_snippet(row['question'])}")
        emit(f"      A: {_snippet(row['answer'])}")
        emit(f"      your note : {row['note'] or '(none)'}")
        emit(f"      judge says: {row['judge_reason'] or '(no reason)'}")
    unreadable = len(rows) - len(usable)
    if unreadable:
        emit(f"\n{unreadable} answer(s) were left out because the judge's reply could not be read.")

    if args.save:
        out_path = os.path.join(BASE_DIR, "docs", "week6", "judge-validation-output.md")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write("# Week 6: judge validation output (generated)\n\n")
            handle.write(f"Generated {datetime.now().isoformat(timespec='seconds')} by "
                         "`python scripts/validate_judge.py --save`. Numbers only: what they mean, "
                         "and whether you trust the judge, is yours to write.\n\n")
            handle.write("```\n" + "\n".join(lines) + "\n```\n")
        print(f"\nsaved: {display_path(out_path, BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
