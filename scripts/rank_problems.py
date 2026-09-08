"""Week 5 step 4 — rank the named problems by frequency x severity.

You cannot fix everything at once, so the last step is deciding what to
fix FIRST. A problem that happens twice but is harmful outranks one that happens six
times but is merely untidy. Multiplying how often it happens by how much it hurts is
the standard way to express that, and it makes the ordering arguable rather than a
matter of taste.

Choosing the target is still yours. This prints the ranking and says which group comes
out on top; the brief asks *you* to pick the one to attack and write down what you
expect to happen before you touch anything.

Run:
    python scripts/rank_problems.py
    python scripts/rank_problems.py --save     # also write docs/week5/ranked-problems.md
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import BASE_DIR                                        # noqa: E402
from app.worksheet import parse, normalize_code, normalize_severity    # noqa: E402
from app.worksheet import normalize_verdict                            # noqa: E402

DEFAULT_IN = os.path.join(BASE_DIR, "docs", "week5", "coded-notes.md")
DEFAULT_OUT = os.path.join(BASE_DIR, "docs", "week5", "ranked-problems.md")

SEVERITY_WORDS = {1: "mildly wrong", 2: "misleading", 3: "confidently wrong"}


def _validate(blocks):
    """Every failure needs a code and a usable severity before it can be ranked."""
    problems = []
    if not blocks:
        problems.append("No `## trace <id>` blocks found — is this the right file?")
        return problems
    for block in blocks:
        trace_id = block["trace_id"]
        if normalize_verdict(block["verdict"]) != "bad":
            problems.append(f"trace {trace_id}: verdict is {block['verdict']!r}, "
                            "expected 'bad' (this file should hold only failures)")
        if not normalize_code(block["code"]):
            problems.append(f"trace {trace_id}: no code — give this failure a group name")
        if normalize_severity(block["severity"]) is None:
            problems.append(f"trace {trace_id}: severity is {block['severity']!r}; "
                            "it must be 1, 2 or 3")
    return problems


def _group(blocks):
    """Collect failures by their code. Returns a list of group dicts, unranked."""
    groups = {}
    for block in blocks:
        key = normalize_code(block["code"])
        group = groups.setdefault(key, {
            "key": key,
            "display": block["code"].strip(),
            "severities": [],
            "traces": [],
        })
        group["severities"].append(normalize_severity(block["severity"]))
        group["traces"].append(block["trace_id"])

    result = []
    for group in groups.values():
        severities = [s for s in group["severities"] if s]
        count = len(severities)
        total = sum(severities)
        result.append({
            **group,
            "count": count,
            "impact": total,                                   # frequency x severity
            "mean_severity": (total / count) if count else 0.0,
            "worst": max(severities) if severities else 0,
        })
    return result


def _near_duplicates(groups):
    """Warn about two group names that are probably the same problem split in two.

    An accidental split ("wrong-doc" and "wrong-document") makes both look rarer than
    the real problem is, which corrupts the ranking. Flagging is all this does — merging
    is a judgement call, so it stays yours.
    """
    warnings = []
    keys = [g["key"] for g in groups]
    for i, left in enumerate(keys):
        for right in keys[i + 1:]:
            left_tokens, right_tokens = set(left.split("-")), set(right.split("-"))
            if not left_tokens or not right_tokens:
                continue
            overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
            if left in right or right in left or overlap >= 0.5:
                warnings.append((left, right, overlap))
    return warnings


def main():
    parser = argparse.ArgumentParser(description="Rank the coded problems to pick a target.")
    parser.add_argument("--in", dest="source", default=DEFAULT_IN,
                        help="the coded notes (default docs/week5/coded-notes.md)")
    parser.add_argument("--save", action="store_true",
                        help="also write the ranking to docs/week5/ranked-problems.md")
    args = parser.parse_args()

    try:
        blocks, metadata = parse(args.source)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        print("Create it first:  python scripts/code_notes.py")
        return 1

    problems = _validate(blocks)
    if problems:
        print(f"Not ready to rank — {len(problems)} thing(s) to fix in "
              f"{os.path.relpath(args.source, BASE_DIR)}:\n")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    groups = _group(blocks)
    # Worst impact first; ties broken by how often it happens, then by name for stability.
    groups.sort(key=lambda g: (-g["impact"], -g["count"], g["key"]))

    try:
        sample_size = int(metadata.get("sample_size", 0))
    except ValueError:
        sample_size = 0

    lines = []

    def emit(text=""):
        print(text)
        lines.append(text)

    emit("=== Ranked problem taxonomy ===")
    emit(f"{len(blocks)} failure(s) across {len(groups)} named group(s)"
         + (f", from {sample_size} traces read" if sample_size else ""))
    emit()
    emit("impact = how often it happened x how much it hurt (the sum of its severities).")
    emit("severity: 1 mildly wrong · 2 misleading · 3 confidently wrong")
    emit()
    emit(f"{'#':<3}{'problem group':<44}{'n':>4}{'mean sev':>10}{'impact':>8}"
         + (f"{'% of read':>11}" if sample_size else ""))
    for position, group in enumerate(groups, start=1):
        share = f"{group['count'] / sample_size:>10.0%}" if sample_size else ""
        emit(f"{position:<3}{group['display'][:43]:<44}{group['count']:>4}"
             f"{group['mean_severity']:>10.2f}{group['impact']:>8}{share:>11}")
    emit()

    emit("--- which traces are in each group ---")
    for group in groups:
        emit(f"  {group['display']}")
        emit(f"    worst severity {group['worst']} "
             f"({SEVERITY_WORDS.get(group['worst'], '?')}) · "
             f"traces: {', '.join(group['traces'])}")
    emit()

    singletons = [g["display"] for g in groups if g["count"] == 1]
    if singletons:
        emit(f"Groups that occurred only once ({len(singletons)}): "
             f"{', '.join(singletons)}")
        emit("  A group of one is not yet a pattern. Either it is genuinely rare, or it "
             "belongs inside a bigger group. Decide deliberately, and say which.")
        emit()

    duplicates = _near_duplicates(groups)
    if duplicates:
        emit("Possible accidental splits — these names look like the same problem:")
        for left, right, overlap in duplicates:
            emit(f"  - {left!r} vs {right!r}  (name overlap {overlap:.0%})")
        emit("  If they are the same, merge them in coded-notes.md and re-run. A split "
             "problem looks rarer than it is and can lose its place in the ranking.")
        emit()

    top = groups[0]
    emit(f"Highest impact: {top['display']} "
         f"({top['count']} occurrence(s), impact {top['impact']})")
    emit()
    emit("That is the ranking, not the decision. The brief asks you to choose the target "
         "yourself and write down what you expect to happen BEFORE changing anything — "
         "so that next week's measurement has a prediction to test. Write both into "
         "docs/week5/taxonomy.md.")

    if args.save:
        os.makedirs(os.path.dirname(DEFAULT_OUT), exist_ok=True)
        with open(DEFAULT_OUT, "w", encoding="utf-8") as f:
            f.write("# Week 5 — ranked problems (generated)\n\n")
            f.write(f"Generated {datetime.now().isoformat(timespec='seconds')} by "
                    "`python scripts/rank_problems.py --save`. "
                    "Do not hand-edit; edit `coded-notes.md` and re-run.\n\n")
            f.write("```\n" + "\n".join(lines) + "\n```\n")
        print(f"\nSaved: {os.path.relpath(DEFAULT_OUT, BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
