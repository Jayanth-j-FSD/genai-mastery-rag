"""Week 4, mentor checks #3 and #4 — measure retrieval before and after the change.

This asks every labelled question twice, once with the Week 3 search
("dense") and once with this week's search ("hybrid"), and reports how often the
right document showed up. That difference IS the before-and-after number. It also
prints, by name, the questions the change did NOT fix — which is the honest half
that people usually leave out.

Only the search runs here, never the answer model, so this is cheap: one small
embedding call per question per mode and no answer generation at all.

Run:
    python scripts/eval_retrieval.py
    python scripts/eval_retrieval.py --save      # also write docs/week4/eval-results.md
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings, BASE_DIR          # noqa: E402
from app.console import display_path               # noqa: E402
from app.rag.retriever import retrieve_for_mode    # noqa: E402
from tests.eval_set import in_corpus_cases         # noqa: E402

MODES = ["dense", "hybrid"]        # "before" and "after"
BASE_K_VALUES = [1, 3, 5]          # report hit-rate at each of these depths


def _k_values():
    """The depths to report, always including the configured eval_k.

    If someone sets EVAL_K=10 in .env, hit-rate@10 has to be one of the reported
    depths AND has to be retrieved for — otherwise the highlighted number would be
    silently capped at 5 and read as a genuine miss.
    """
    return sorted(set(BASE_K_VALUES + [settings.eval_k]))


def _first_expected_rank(chunks, expected_sources):
    """1-based rank of the first chunk from an acceptable document, or None."""
    for rank, chunk in enumerate(chunks, start=1):
        if chunk.get("source") in expected_sources:
            return rank
    return None


def _measure(mode, depth):
    """Retrieve once per in-corpus question and record where the right document landed."""
    rows = []
    for case in in_corpus_cases():
        chunks = retrieve_for_mode(case["question"], depth, mode)
        rows.append({
            "id": case["id"],
            "question": case["question"],
            "expected_sources": case["expected_sources"],
            "favours": case["favours"],
            "rank": _first_expected_rank(chunks, case["expected_sources"]),
            "top_sources": [c.get("source") for c in chunks],
        })
    return rows


def _hit_rate(rows, k):
    """Fraction of questions where an acceptable document appears in the top k."""
    if not rows:
        return 0, 0, 0.0
    hits = sum(1 for row in rows if row["rank"] is not None and row["rank"] <= k)
    return hits, len(rows), hits / len(rows)


def _mrr(rows):
    """Mean Reciprocal Rank: 1/rank of the first right document, averaged (0 when missed).
    Rewards putting the right document at the very top, not merely somewhere in the list."""
    if not rows:
        return 0.0
    total = sum((1.0 / row["rank"]) if row["rank"] else 0.0 for row in rows)
    return total / len(rows)


def _verdict(before_rank, after_rank, k):
    """Compare one question's outcome across the two modes at depth k."""
    before_hit = before_rank is not None and before_rank <= k
    after_hit = after_rank is not None and after_rank <= k
    if before_hit and after_hit:
        return "both found"
    if not before_hit and after_hit:
        return "FIXED"
    if before_hit and not after_hit:
        return "REGRESSED"
    return "STILL BROKEN"


def _prediction_note(favours, verdict):
    """Did the hypothesis written in eval_set.py match what actually happened?

    Returns a short verdict string, or None when the case predicted nothing.
    A prediction of "keyword" only counts as held if dense genuinely missed the
    question and the change rescued it — if dense found it all along, the guess
    that it needed keyword search was simply wrong.
    """
    if favours == "keyword":
        return {
            "FIXED": "held — keyword search rescued it",
            "both found": "wrong — dense already found it",
            "STILL BROKEN": "wrong — keyword did not rescue it",
            "REGRESSED": "wrong — hybrid lost a question dense had",
        }.get(verdict)
    if favours == "dense":
        return {
            "both found": "held — dense found it and hybrid kept it",
            "REGRESSED": "held for dense, but hybrid lost it",
            "STILL BROKEN": "wrong — dense did not find it either",
            "FIXED": "wrong — dense missed it and keyword rescued it",
        }.get(verdict)
    return None            # "either" makes no prediction to check


def _rank_display(rank, k):
    """Show a rank only if it is within the graded depth, else a dash."""
    return str(rank) if rank is not None and rank <= k else "-"


def main():
    parser = argparse.ArgumentParser(description="Measure retrieval before vs after.")
    parser.add_argument("--save", action="store_true",
                        help="also write the report to docs/week4/eval-results.md")
    args = parser.parse_args()

    k_values = _k_values()
    depth = max(k_values)               # retrieve deep enough for every reported k
    eval_k = settings.eval_k

    results = {}
    for mode in MODES:
        try:
            results[mode] = _measure(mode, depth)
        except RuntimeError as exc:          # missing documents, no API key configured
            print(f"Error: {exc}")
            return 1
        except Exception as exc:            # e.g. a rejected API key, or no index yet
            print(f"Error ({type(exc).__name__}): {exc}")
            print("Have you run `python scripts/ingest.py` and set OPENAI_API_KEY in .env?")
            return 1

    rows_before, rows_after = results["dense"], results["hybrid"]
    if not rows_before:
        print("No in-corpus cases in tests/eval_set.py — nothing to measure.")
        return 1

    by_id_before = {row["id"]: row for row in rows_before}
    by_id_after = {row["id"]: row for row in rows_after}

    lines = []

    def emit(text=""):
        print(text)
        lines.append(text)

    emit("=== Retrieval quality: dense (Week 3) vs hybrid (Week 4) ===")
    emit(f"corpus questions measured: {len(rows_before)}   "
         f"(refusal-only cases excluded — they have no expected document)")
    emit(f"settings: top_k={settings.top_k}, hybrid_candidates={settings.hybrid_candidates}, "
         f"rrf_k={settings.rrf_k}, chunk_size={settings.chunk_size}")
    emit()

    emit(f"{'metric':<14}{'dense':>10}{'hybrid':>10}{'change':>10}")
    for k in k_values:
        before_hits, total, before_rate = _hit_rate(rows_before, k)
        after_hits, _, after_rate = _hit_rate(rows_after, k)
        marker = "   <- the mentor's number" if k == eval_k else ""
        emit(f"{'hit-rate@' + str(k):<14}"
             f"{f'{before_hits}/{total}':>10}"
             f"{f'{after_hits}/{total}':>10}"
             f"{f'{after_rate - before_rate:+.1%}':>10}{marker}")
    emit(f"{'MRR':<14}{_mrr(rows_before):>10.3f}{_mrr(rows_after):>10.3f}"
         f"{_mrr(rows_after) - _mrr(rows_before):>+10.3f}")
    emit(f"(MRR is over the top {depth} retrieved, not capped at k={eval_k}.)")
    emit()

    # Per-question detail at the graded depth.
    emit(f"--- per question, at k={eval_k} "
         f"(rank of the first acceptable document; '-' = not in the top {eval_k}) ---")
    emit(f"{'case':<28}{'dense':>7}{'hybrid':>8}   verdict")
    verdicts = {}
    for case_id in [row["id"] for row in rows_before]:
        before_rank = by_id_before[case_id]["rank"]
        after_rank = by_id_after[case_id]["rank"]
        verdict = _verdict(before_rank, after_rank, eval_k)
        verdicts[case_id] = verdict
        emit(f"{case_id:<28}{_rank_display(before_rank, eval_k):>7}"
             f"{_rank_display(after_rank, eval_k):>8}   {verdict}")
    emit()

    # The three lists that matter to the mentor.
    for label, wanted in (
        ("FIXED by the change", "FIXED"),
        ("NOT fixed by the change (still broken)", "STILL BROKEN"),
        ("BROKEN by the change (a regression)", "REGRESSED"),
    ):
        matching = [case_id for case_id, verdict in verdicts.items() if verdict == wanted]
        emit(f"{label}: {len(matching)}")
        for case_id in matching:
            case = by_id_before[case_id]
            emit(f"  - {case_id}: {case['question']}")
            emit(f"      expected {case['expected_sources']}, "
                 f"hybrid fetched {by_id_after[case_id]['top_sources'][:eval_k]}")
        emit()

    # Were the predictions in eval_set.py right?
    emit("--- predictions from eval_set.py ---")
    for case_id, verdict in verdicts.items():
        favours = by_id_before[case_id]["favours"]
        note = _prediction_note(favours, verdict)
        if note is None:
            continue                      # "either" predicted nothing to check
        emit(f"  {case_id:<28} predicted {favours:<8} -> {note}")
    emit()
    emit("Note on the metric: hit-rate@k is 'did an acceptable document appear in the "
         "top k'. Two cases list two documents, either of which is a correct source, so "
         "one of them appearing is a hit. Recall@k is not reported separately because "
         "with one relevant document per question it is the same number.")

    if args.save:
        out_path = os.path.join(BASE_DIR, "docs", "week4", "eval-results.md")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("# Week 4 — retrieval evaluation output\n\n")
            f.write(f"Generated {datetime.now().isoformat(timespec='seconds')} by "
                    "`python scripts/eval_retrieval.py --save`.\n\n")
            f.write("```\n" + "\n".join(lines) + "\n```\n")
        print(f"\nSaved: {display_path(out_path, BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
