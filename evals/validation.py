"""Judge validation: build a blind grading sheet, then compare the human's verdicts with the judge's.

You cannot trust a judge you have not checked. The check is simple. A sample of the
answers goes into a sheet. YOU grade them without seeing what the judge said (that is what "blind"
means: otherwise you would be nudged towards agreeing). Then the judge's hidden verdicts are lined up
against yours and `agreement.py` counts how often you agree.

The sheet reuses Week 5's plain-markdown format (`## trace <id>` blocks with `- verdict:` and
`- note:` lines), so one parser (`app/worksheet.py`) reads both. Verdicts are `ok` (the answer is
acceptable) or `bad` (it is not), exactly as in Week 5; `ok` means the judge's "pass".

Which answers go in the sheet matters. If the app is right 95% of the time, a random sample is mostly
good answers and tells you almost nothing about whether the judge can spot a bad one. So the sample
puts the answers the rules or the judge flagged first (up to half the sheet) and fills the rest at
random, then shuffles, so the bad ones are not bunched together.
"""
import json
import os
import random
import re

from app import worksheet
from app.config import BASE_DIR

DIRECTORY = os.path.join(BASE_DIR, "evals", "judge_validation")
SHEET_PATH = os.path.join(DIRECTORY, "sheet.md")
ITEMS_PATH = os.path.join(DIRECTORY, "items.json")


def collect_items(runs):
    """Every judged answer from the given runs, skipping unreadable verdicts and repeated answers."""
    items, seen = [], set()
    for run in runs:
        label = run["meta"]["label"]
        for entry in run["cases"]:
            judged = entry.get("judge")
            if not judged or judged.get("verdict") not in ("pass", "fail"):
                continue
            key = (entry["id"], entry["answer"])
            if key in seen:
                continue
            seen.add(key)
            items.append({"run": label, "entry": entry})
    return items


def pick_sample(items, n, seed):
    """Up to n items: the flagged ones first (at most half), then random others, shuffled. Ids j01..."""
    rng = random.Random(seed)
    flagged = [i for i in items if not i["entry"]["passed"] or i["entry"]["judge"]["verdict"] == "fail"]
    others = [i for i in items if i not in flagged]
    rng.shuffle(flagged)
    rng.shuffle(others)
    chosen = flagged[: n // 2]
    chosen += others[: max(n - len(chosen), 0)]
    if len(chosen) < n:                                   # not enough unflagged ones: top up with the rest
        chosen += [i for i in flagged[n // 2:] if i not in chosen][: n - len(chosen)]
    rng.shuffle(chosen)
    for number, item in enumerate(chosen, start=1):
        item["sheet_id"] = f"j{number:02d}"
    return chosen


def _one_line(text):
    return re.sub(r"\s+", " ", (text or "").replace("\n", " / ")).strip()


def render_sheet(sample, seed):
    """The blind sheet as markdown. It shows what the judge was shown, and never what it decided."""
    out = ["# Week 6: judge validation sheet (blind)", "",
           f"<!-- sample_size: {len(sample)} -->", f"<!-- seed: {seed} -->", "",
           "## How to fill this in", "",
           "You are the grader. For each block, read the QUESTION, the CONTEXT the system was shown, the",
           "REFERENCE answer and the system's ANSWER, and decide whether the answer is acceptable:", "",
           "- `ok`  the answer is faithful to the context, answers what was asked, handles absence honestly",
           "  (a refusal is right only when the context lacks the answer), and, if two documents disagree,",
           "  says so or names the document it used.",
           "- `bad` anything less: an invented fact, a missing part of a list, a different question answered,",
           "  a refusal when the context had the answer, a confident answer when it did not.", "",
           "Fill `verdict:` with `ok` or `bad` on every block. A short `note:` on each `bad` helps you later.",
           "You are not shown what the judge or the rule checks decided, on purpose.",
           "Then run `python scripts/validate_judge.py`.", "", "---", ""]
    for item in sample:
        entry = item["entry"]
        out += [f"## trace {item['sheet_id']}", "", f"**Question:** {_one_line(entry['question'])}", "",
                "**Context the system was shown:**", ""]
        for number, chunk in enumerate(entry["retrieved"], start=1):
            out.append(f"{number}. `{chunk['source']}`: {_one_line(chunk['text'])}")
        if not entry["retrieved"]:
            out.append("(nothing was retrieved)")
        out += ["", f"**Reference:** {_one_line(entry['reference']) or '(none written)'}", "",
                f"**Answer:** {_one_line(entry['answer'])}", "", "- verdict: ", "- note: ", "", "---", ""]
    return "\n".join(out) + "\n"


def hidden_mapping(sample, seed):
    """What the judge said about each sheet id. Kept in a separate file so the sheet stays blind."""
    return {"seed": seed, "n": len(sample), "items": {
        item["sheet_id"]: {"run": item["run"], "case_id": item["entry"]["id"],
                           "problem_type": item["entry"]["problem_type"],
                           "judge_verdict": item["entry"]["judge"]["verdict"],
                           "judge_reason": item["entry"]["judge"].get("reason", ""),
                           "judge_model": item["entry"]["judge"].get("model", ""),
                           "rules_passed": item["entry"]["passed"],
                           "question": item["entry"]["question"], "answer": item["entry"]["answer"]}
        for item in sample}}


def write_sheet(sample, seed, sheet_path=SHEET_PATH, items_path=ITEMS_PATH):
    os.makedirs(os.path.dirname(sheet_path), exist_ok=True)
    with open(sheet_path, "w", encoding="utf-8") as handle:
        handle.write(render_sheet(sample, seed))
    with open(items_path, "w", encoding="utf-8") as handle:
        json.dump(hidden_mapping(sample, seed), handle, ensure_ascii=False, indent=1)


def join_labels(sheet_path=SHEET_PATH, items_path=ITEMS_PATH):
    """Line the human's verdicts up with the judge's. Returns (rows, problems).

    Each row is {"id", "human", "judge", "note", ...the hidden fields}. `problems` lists everything
    unfinished, and the caller must refuse to compute anything while it is non-empty: agreement
    on a half-graded sheet would be a number about nothing.
    """
    blocks, _ = worksheet.parse(sheet_path)
    with open(items_path, encoding="utf-8") as handle:
        hidden = json.load(handle)["items"]
    problems, rows = [], []
    if not blocks:
        return [], ["No `## trace <id>` blocks found: is this the right file?"]
    for block in blocks:
        verdict = worksheet.normalize_verdict(block["verdict"])
        if verdict is None:
            problems.append(f"{block['trace_id']}: verdict is {block['verdict']!r}; it must be ok or bad")
            continue
        info = hidden.get(block["trace_id"])
        if info is None:
            problems.append(f"{block['trace_id']}: not in {os.path.basename(items_path)}; was the sheet regenerated?")
            continue
        rows.append({"id": block["trace_id"], "human": "pass" if verdict == "ok" else "fail",
                     "note": block["note"], **info})
    return rows, problems
