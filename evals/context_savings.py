"""Week 11: for free, how much of the prompt could each cost idea remove, and does it still leave the answer?

A request costs what you send (input tokens) plus what the model writes (output tokens). On this app
the input is almost all the retrieved passages, and a lot of those are lines the handbook repeats under every section.
Before spending any quota on an idea ("do not show the model those lines", "retrieve one passage fewer"), this asks two
cheap questions of every eval question, using only retrieval, which is free, local and exact:

  1. How many characters of the prompt would the idea remove?
  2. Is the answer still in front of the model afterwards? Two ways it can not be: a document the case needs is no
     longer there (a passage was dropped), or a fact string that WAS in the prompt is gone (a line was taken out).

Characters are not tokens, and the screen does not pretend they are: tokens follow characters to a first approximation, and
the live run measures them. What the screen CAN say for certain is "this idea fails the case": if the answer is not in the
prompt, no model will find it. It cannot say the idea is safe, only that nothing checkable is lost.
"""
import statistics

from app.rag import generator
from evals import checks, screen


def prompt_chars(question, chunks):
    """How many characters the model would be sent: the instructions plus the passages plus the question."""
    return len(generator.SYSTEM_PROMPT) + len(generator.user_prompt(question, generator.format_context(chunks)))


def first_copy_only(chunks):
    """Candidate C, screened but not built: each non-heading line is shown once per document, in the first passage that has it.

    The other ideas look at a document's whole text to decide what is boilerplate; this one looks only at what is in front
    of the model, so it also drops a line that is merely repeated between the four passages. Passages left empty are dropped."""
    seen, shown = {}, []
    for chunk in chunks:
        already = seen.setdefault(chunk["source"], set())
        kept = []
        for line in chunk["text"].splitlines():
            tidy = " ".join(line.split())
            if tidy and not tidy.startswith("#") and tidy in already:
                continue
            if tidy:
                already.add(tidy)
            kept.append(line)
        text = "\n".join(kept)
        if text.strip():
            shown.append(dict(chunk, text=text))
    return shown


def _documents_with_a_useful_passage(chunks, case):
    """The expected documents that have at least one passage holding one of the case's fact strings (see evals/screen.py)."""
    return {name for name in case["expected_sources"]
            if screen.first_useful_rank([c for c in chunks if c["source"] == name], dict(case, expected_sources=[name])) is not None}


def _facts_in(chunks, case):
    """The case's fact strings that appear in the passages of the documents the case expects, tidied the way the answer checks
    tidy them. A string in a passage of some other document is not the answer: the word "remove" sits in a line of handbook
    boilerplate, and that is not what a question about the Nexora policy is looking for."""
    text = " ".join(chunk["text"] for chunk in chunks if chunk["source"] in case["expected_sources"])
    phrases = list(case.get("expect_all") or []) + list(case.get("expect_contains") or [])
    return {phrase for phrase in phrases if checks.contains_phrase(text, phrase, bool(case.get("whole_words")))}


def screen_case(case, baseline, shown):
    """What one idea does to one case, as plain numbers. `baseline` and `shown` are the passages before and after the idea."""
    before, after = prompt_chars(case["question"], baseline), prompt_chars(case["question"], shown)
    result = {"id": case["id"], "problem_type": case.get("problem_type", ""), "answerable": bool(case["expected_sources"]),
              "chars_before": before, "chars_after": after, "saved": before - after,
              "saved_share": (before - after) / before if before else 0.0,
              "passages_before": len(baseline), "passages_after": len(shown), "lost_documents": [], "lost_facts": []}
    if result["answerable"]:
        result["lost_documents"] = sorted(_documents_with_a_useful_passage(baseline, case) - _documents_with_a_useful_passage(shown, case))
        result["lost_facts"] = sorted(_facts_in(baseline, case) - _facts_in(shown, case))
    return result


def screen_all(cases_and_chunks, candidates):
    """{candidate name: [screen_case result per case]}. `cases_and_chunks` is [(case, retrieved passages)], `candidates` is
    {name: function from the retrieved passages to the passages the model would be shown}."""
    return {name: [screen_case(case, chunks, shape([dict(c) for c in chunks])) for case, chunks in cases_and_chunks]
            for name, shape in candidates.items()}


def summarize(rows):
    """One candidate's rows as the numbers a report prints."""
    shares = [row["saved_share"] for row in rows]
    return {"n": len(rows), "chars_before": statistics.mean(row["chars_before"] for row in rows),
            "chars_after": statistics.mean(row["chars_after"] for row in rows),
            "mean_saved_share": statistics.mean(shares), "median_saved_share": statistics.median(shares),
            "max_saved_share": max(shares), "zero_saving": sum(1 for row in rows if row["saved"] == 0),
            "lost_documents": {row["id"]: row["lost_documents"] for row in rows if row["lost_documents"]},
            "lost_facts": {row["id"]: row["lost_facts"] for row in rows if row["lost_facts"]}}


def kind_lines(rows):
    """One line per kind of question for one idea (the eval questions, and the bank's stand-in traffic when it was drawn)."""
    lines = []
    for kind, wanted in (("eval questions", True), ("bank questions", False)):
        group = [row for row in rows if (row["problem_type"] != "bank") == wanted]
        if group:
            lines.append(f"  {kind:<16}{len(group):>3}   mean saved {statistics.mean(r['saved_share'] for r in group):.1%}, "
                         f"mean prompt {statistics.mean(r['chars_before'] for r in group):.0f} to {statistics.mean(r['chars_after'] for r in group):.0f} characters")
    return lines


def format_report(table, header_lines=()):
    """Printable lines for {candidate: rows}. A candidate that loses a document or a fact string on any case is marked FAILS."""
    lines = list(header_lines)
    lines += [f"{'idea':<34}{'chars':>8}{'after':>8}{'saved':>8}{'median':>8}{'max':>8}{'no saving':>12}{'screen':>9}", ""]
    notes = []
    for name, rows in table.items():
        summary = summarize(rows)
        failed = summary["lost_documents"] or summary["lost_facts"]
        none_saved = f"{summary['zero_saving']} of {summary['n']}"
        lines.append(f"{name:<34}{summary['chars_before']:>8.0f}{summary['chars_after']:>8.0f}{summary['mean_saved_share']:>8.1%}"
                     f"{summary['median_saved_share']:>8.1%}{summary['max_saved_share']:>8.1%}{none_saved:>12}"
                     f"{'FAILS' if failed else 'passes':>9}")
        for case_id, documents in summary["lost_documents"].items():
            notes.append(f"  {name}: {case_id} no longer shows a passage with the answer from {documents}")
        for case_id, facts in summary["lost_facts"].items():
            notes.append(f"  {name}: {case_id} no longer shows {facts}")
    lines += ["", "what a FAILS idea loses (a document the case needs, or a fact string that was in the prompt):"] + (notes or ["  (nothing)"])
    return lines
