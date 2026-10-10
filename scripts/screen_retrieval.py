"""Week 6: screen retrieval configurations for free, before spending any model quota.

For each configuration this builds (once) a private index, asks the 37 answerable eval
questions, and reports how many have a passage that holds the answer in the top 4, 6, 8 and 10. It makes
NO model calls, so it costs nothing and gives the same numbers every time. It shows which cases a
retrieval change could possibly fix, and which failures are not about retrieval at all.

Run:
    python scripts/screen_retrieval.py
    python scripts/screen_retrieval.py --ks 3 5 10
"""
import argparse
import os
import sys

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.console import make_output_safe        # noqa: E402
from app.rag import retriever                   # noqa: E402
from evals import runner, screen                # noqa: E402
from evals.cases import all_cases               # noqa: E402

# Each configuration differs from the baseline by the settings shown, and the baseline is first.
CONFIGURATIONS = {
    "dense (baseline)": {"retrieval_mode": "dense"},
    "dense + strip": {"retrieval_mode": "dense", "boilerplate_min_repeats": 10},
    "hybrid": {"retrieval_mode": "hybrid"},
    "hybrid + strip": {"retrieval_mode": "hybrid", "boilerplate_min_repeats": 10},
}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Retrieval-only screen of the eval set.")
    parser.add_argument("--ks", type=int, nargs="+", default=[4, 6, 8, 10], help="the k values to report")
    args = parser.parse_args(argv)
    make_output_safe()

    cases = [case for case in all_cases() if case["expected_sources"]]
    table, chunk_counts = {}, {}
    for name, overrides in CONFIGURATIONS.items():
        ranks = {}
        with runner.overridden(overrides), runner.isolated_index() as (_collection, count):
            for case in cases:
                chunks = retriever.retrieve_for_mode(case["question"], max(args.ks), overrides["retrieval_mode"])
                ranks[case["id"]] = screen.first_useful_rank(chunks, case)
        table[name], chunk_counts[name] = ranks, count
    print("\n".join(screen.format_screen(table, sorted(args.ks), chunk_counts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
