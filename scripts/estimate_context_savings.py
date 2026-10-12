"""Week 11: for free, how much of the prompt could each cost idea remove, and does it still leave the answer?

A request costs what you send plus what the model writes, and here what you send is mostly the retrieved passages,
a lot of which are lines the handbook repeats under every section. Before spending any quota on an idea, this asks every eval
question what the prompt would be with the idea applied, using only retrieval (free, local, exact), and reports how many
characters it removes and whether the passage or the fact string the answer needs is still there. It makes NO model calls.

The ideas screened (the first is built, behind CONTEXT_STRIP_MIN_REPEATS; the other two are screened and not built):
  A  take out the lines a document repeats N or more times, from what the model is shown (the index and the search are untouched)
  B  retrieve one passage fewer (TOP_K - 1)
  C  show each line once per document, in the first passage that has it

Run:
    python scripts/estimate_context_savings.py
    python scripts/estimate_context_savings.py --per-case            # one line per question for idea A
    python scripts/estimate_context_savings.py --bank 30 --seed 42   # also 30 questions from the Week 5 bank
    python scripts/estimate_context_savings.py --min-repeats 6

It needs the local embedding model (EMBED_PROVIDER=local, see scripts/download_model.py) and refuses to spend API quota on embeddings.
Characters are not tokens; scripts/measure_cost.py measures tokens.
"""
import argparse
import os
import sys

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings                           # noqa: E402
from app.console import make_output_safe                  # noqa: E402
from app.rag import generator, retriever                  # noqa: E402
from evals import bank, context_savings, runner           # noqa: E402


def candidates(min_repeats, top_k):
    """The ideas, each a function from the retrieved passages to the passages the model would be shown."""
    ideas = {f"A strip lines repeated {min_repeats}+ times": lambda chunks: generator.strip_context(chunks, min_repeats)[0]}
    if top_k >= 2:
        ideas[f"B retrieve {top_k - 1} passages, not {top_k}"] = lambda chunks: chunks[:top_k - 1]
    ideas["C show each line once per document"] = context_savings.first_copy_only
    return ideas


def per_case_lines(rows):
    """One line per question for one idea: how many characters it removes, and what it loses."""
    lines = [f"{'question':<34}{'type':<24}{'chars':>7}{'saved':>8}{'passages':>10}  loses"]
    for row in sorted(rows, key=lambda r: -r["saved_share"]):
        loses = ", ".join(row["lost_documents"] + row["lost_facts"]) or "-"
        lines.append(f"{row['id']:<34}{row['problem_type']:<24}{row['chars_before']:>7}{row['saved_share']:>8.1%}"
                     f"{str(row['passages_before']) + ' to ' + str(row['passages_after']):>10}  {loses}")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description="Screen the cost ideas for free: characters removed, and what is lost.")
    parser.add_argument("--min-repeats", type=int, default=10, help="idea A: take out lines a document repeats this many times (default 10)")
    parser.add_argument("--only", nargs="+", metavar="ID", help="screen only these eval case ids")
    parser.add_argument("--bank", type=int, default=0, metavar="N", help="also draw N questions from the Week 5 bank (no expected answers: only characters)")
    parser.add_argument("--seed", type=int, default=42, help="seed for the bank draw (default 42)")
    parser.add_argument("--per-case", action="store_true", help="also print one line per question for idea A")
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="override ONE setting for this run, e.g. --set top_k=6 (repeatable)")
    args = parser.parse_args(argv)
    make_output_safe()

    if args.min_repeats < 2:
        print("Error: --min-repeats must be 2 or more (1 would take out every line).")
        return 1
    try:
        overrides = runner.parse_overrides(args.set)
        cases = runner.select_cases(args.only, base_only=True)            # the 41 base cases, whatever failures have been converted since
        with runner.overridden(overrides):
            pass                                              # validate now, so a bad value fails before anything runs
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    try:
        with runner.overridden(overrides):
            if settings.embed_provider != "local":
                print("Error: this screen is free only with local embeddings. Set EMBED_PROVIDER=local (python scripts/download_model.py "
                      "fetches the model); it will not spend API quota on embeddings.")
                return 1
            questions = bank.sample(bank.load_questions(), args.bank, args.seed, exclude=[case["question"] for case in cases]) if args.bank else []
            stand_ins = [{"id": f"bank-{number}", "question": question, "problem_type": "bank", "expected_sources": [],
                          "expect_contains": [], "expect_all": []} for number, question in enumerate(questions, start=1)]
            with runner.isolated_index() as (_collection, chunk_count):
                pairs = [(case, retriever.retrieve_for_mode(case["question"], settings.top_k, settings.retrieval_mode))
                         for case in cases + stand_ins]
                table = context_savings.screen_all(pairs, candidates(args.min_repeats, settings.top_k))
            header = [f"free screen: {len(cases)} eval questions" + (f" and {len(stand_ins)} from the Week 5 bank (seed {args.seed})" if stand_ins else "")
                      + f", retrieval {settings.retrieval_mode}, top_k {settings.top_k}, {chunk_count} chunks, no model calls",
                      "chars = mean prompt characters (instructions + passages + question) before the idea; after = with it; saved = the share removed", ""]
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1

    print("\n".join(context_savings.format_report(table, header)))
    first = next(iter(table))
    print("\n" + first + ", by kind of question:")
    print("\n".join(context_savings.kind_lines(table[first])))
    if args.per_case:
        print("\n" + first + ", question by question:")
        print("\n".join(per_case_lines(table[first])))
    print("\nCharacters are not tokens: tokens follow characters to a first approximation and scripts/measure_cost.py measures them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
