"""Week 4 — the inspection view: question / what was fetched / final answer, side by side.

This is the single most useful debugging tool in the whole project.
Every answer the app gives is logged; this prints those logs in a readable shape so
you can see, for one question, exactly which chunks arrived and what the model did
with them. Almost every "why did it say that?" is obvious once you can see all three
columns at once.

The same view is available in the browser at http://127.0.0.1:8000/inspect when the
API is running.

Run:
    python scripts/inspect_traces.py                 # the last 10 requests
    python scripts/inspect_traces.py --last 30
    python scripts/inspect_traces.py --ungrounded     # only the "I don't know" answers
    python scripts/inspect_traces.py --find leave     # only questions mentioning "leave"
    python scripts/inspect_traces.py --trace 3f9ac210 # one trace, with full chunk text
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings          # noqa: E402
from app.rag.diagnose import snippet     # noqa: E402
from app.tracing import read_traces      # noqa: E402


def _print_trace(trace, full_text=False):
    """Print one trace as three labelled sections."""
    config = trace.get("config") or {}
    header = (f"#{trace.get('line_no')}  {trace.get('trace_id', '-')}  "
              f"{trace.get('ts', '')}  mode={config.get('retrieval_mode', '?')}  "
              f"top_k={config.get('top_k', '?')}  chunk_size={config.get('chunk_size', '?')}")
    print(header)
    print("-" * len(header))
    print(f"QUESTION : {trace.get('question', '')}")

    retrieved = trace.get("retrieved") or []
    print(f"FETCHED  : {len(retrieved)} chunk(s)")
    for rank, chunk in enumerate(retrieved, start=1):
        found_by = "+".join(chunk.get("retrievers") or []) or "?"
        ranks = []
        if chunk.get("dense_rank") is not None:
            ranks.append(f"dense#{chunk['dense_rank']}")
        if chunk.get("keyword_rank") is not None:
            ranks.append(f"keyword#{chunk['keyword_rank']}")
        detail = f" ({', '.join(ranks)})" if ranks else ""
        score = chunk.get("score")
        score_text = f"{score:.4f}" if isinstance(score, (int, float)) else "n/a"
        print(f"   {rank}. {chunk.get('source', 'unknown'):<22} score={score_text:<8} "
              f"via {found_by}{detail}")
        text = chunk.get("text", "")
        print(f"      {text if full_text else snippet(text)}")

    grounded = trace.get("grounded")
    print(f"ANSWER   : {trace.get('answer', '')}")
    print(f"GROUNDED : {grounded}"
          + ("   (refused — said it does not know)" if grounded is False else ""))
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Show logged requests as question / fetched / answer.")
    parser.add_argument("--last", type=int, default=10,
                        help="how many recent requests to show (default 10, 0 = all)")
    parser.add_argument("--ungrounded", action="store_true",
                        help="only requests the app refused to answer")
    parser.add_argument("--find", metavar="TEXT",
                        help="only requests whose question contains TEXT")
    parser.add_argument("--trace", metavar="ID",
                        help="show a single trace by its id, with the full chunk text")
    args = parser.parse_args()

    traces = read_traces()
    if not traces:
        print(f"No traces yet in {settings.traces_path}")
        print("Ask a question first:  python scripts/ask.py \"how many leave days carry over?\"")
        return 1

    if args.trace:
        wanted = [t for t in traces if t.get("trace_id") == args.trace]
        if not wanted:
            print(f"No trace with id {args.trace!r}. "
                  f"Run without --trace to list recent ids.")
            return 1
        for trace in wanted:
            _print_trace(trace, full_text=True)
        return 0

    # Filters are applied before the "last N" cut, so --last means "N matching requests".
    if args.ungrounded:
        traces = [t for t in traces if t.get("grounded") is False]
    if args.find:
        needle = args.find.lower()
        traces = [t for t in traces if needle in (t.get("question") or "").lower()]

    if not traces:
        print("No traces matched those filters.")
        return 0

    if args.last and args.last > 0:
        traces = traces[-args.last:]

    print(f"=== Inspection view — {len(traces)} request(s) from "
          f"{os.path.basename(settings.traces_path)} ===\n")
    for trace in traces:
        _print_trace(trace)

    refused = sum(1 for t in traces if t.get("grounded") is False)
    print(f"shown: {len(traces)}   refused: {refused}   answered: {len(traces) - refused}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
