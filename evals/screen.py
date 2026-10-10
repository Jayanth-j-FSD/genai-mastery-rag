"""Retrieval-only screening: does the passage that holds the answer even reach the model? (Week 6)

Answering a question takes two steps. RETRIEVAL puts passages in front of the model and
GENERATION writes the answer from them. A model call costs quota, but retrieval is free, local and
exact, so before spending quota on an experiment ask the cheap question first: under this configuration,
does a useful passage land in the top k? If it does not, no prompt or model can rescue the case.

A chunk is "useful" for a case when it comes from one of the case's expected documents AND contains one
of the case's fact strings, so a chunk from the right document but the wrong section does not count. That
is stricter than Week 4's document-level hit-rate. It matched the live result of every run recorded in
docs/week6/CHANGES.md, but it cannot see a generation failure (an incomplete list) or a conflict (a case
that needs two documents is satisfied by one), so a hit here is necessary for a case to pass live, not
sufficient.
"""


def facts_of(case):
    """The lower-cased fact strings a useful chunk may contain. Empty means any chunk from an expected document counts."""
    facts = list(case.get("expect_contains") or []) + list(case.get("expect_all") or [])
    return [" ".join(str(fact).lower().split()) for fact in facts]


def first_useful_rank(chunks, case):
    """The 1-based position of the first useful chunk in `chunks` (best first), or None."""
    expected, facts = set(case["expected_sources"]), facts_of(case)
    for position, chunk in enumerate(chunks, start=1):
        text = " ".join(chunk["text"].lower().split())
        if chunk["source"] in expected and (not facts or any(fact in text for fact in facts)):
            return position
    return None


def hit_counts(ranks, ks):
    """{k: how many cases have a useful chunk within the top k}. `ranks` maps case id to a rank or None."""
    return {k: sum(1 for rank in ranks.values() if rank is not None and rank <= k) for k in ks}


def format_screen(table, ks, chunk_counts):
    """Printable lines. `table` is {configuration: {case id: rank or None}}, `chunk_counts` {configuration: chunks}."""
    names = list(table)
    n_cases = len(next(iter(table.values()))) if table else 0
    width = {name: max(len(name) + 2, 14) for name in names}
    lines = [f"retrieval-only screen: {n_cases} answerable cases, no model calls",
             "a case is a hit at k when a chunk from an expected document that contains one of its fact strings is in the top k", "",
             f"{'configuration':<22}{'chunks':>7}" + "".join(f"{'top ' + str(k):>8}" for k in ks)]
    for name in names:
        counts = hit_counts(table[name], ks)
        lines.append(f"{name:<22}{chunk_counts.get(name, 0):>7}" + "".join(f"{counts[k]:>8}" for k in ks))
    first = min(ks)
    weak = [case_id for case_id in table[names[0]]
            if any(table[name][case_id] is None or table[name][case_id] > first for name in names)]
    lines += ["", f"cases with no useful chunk in the top {first} under at least one configuration "
                  f"(rank of the first useful chunk, - = not in the top {max(ks)}):",
              f"{'case':<34}" + "".join(f"{name:>{width[name]}}" for name in names)]
    for case_id in weak:
        lines.append(f"{case_id:<34}" + "".join(
            f"{('-' if table[name][case_id] is None else table[name][case_id]):>{width[name]}}" for name in names))
    if not weak:
        lines.append("(none)")
    return lines
