"""Week 5 step 2 — draw a FAIR sample of traces and write a reading worksheet.

The temptation is to look through your logs and pick the interesting
ones. That is called curating, and it hides the problems you did not already suspect.
Instead this takes a random sample, using a fixed seed so the exact same draw can be
reproduced by anyone — which is how you prove the sample was not cherry-picked. That
is the first thing the mentor checks.

The worksheet it writes deliberately offers NO list of categories. The brief is
explicit that the honest note comes first and the grouping comes afterwards; if the
sheet suggested categories you would find yourself sorting into them instead of
describing what you actually saw.

Run:
    python scripts/ask_batch.py            # first, so there are traces to sample
    python scripts/sample_traces.py --n 20
    python scripts/sample_traces.py --n 20 --seed 7 --force
"""
import argparse
import os
import random
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings, BASE_DIR        # noqa: E402
from app.tracing import read_traces              # noqa: E402

DEFAULT_OUT = os.path.join(BASE_DIR, "docs", "week5", "worksheet.md")


def _one_line(text):
    """Flatten text onto a single line.

    Questions and answers are written as `**Answer:** ...` on one line, and the parser
    in app/worksheet.py reads one line per field. A model answer containing a bullet
    list would otherwise be silently truncated at its first newline when carried into
    the coded notes, so the newlines are replaced rather than left to break it.
    """
    return re.sub(r"\s+", " ", (text or "").replace("\n", " / ")).strip()


def _fetched_summary(trace):
    """One compact line per fetched chunk: which document, how well it scored, found how."""
    rows = []
    for rank, chunk in enumerate(trace.get("retrieved") or [], start=1):
        score = chunk.get("score")
        score_text = f"{score:.3f}" if isinstance(score, (int, float)) else "n/a"
        found_by = "+".join(chunk.get("retrievers") or []) or "?"
        rows.append(f"  {rank}. {chunk.get('source', 'unknown')} "
                    f"(score {score_text}, via {found_by})")
    return "\n".join(rows) or "  (nothing was fetched)"


def _worksheet(sample, population_size, seed, requested):
    """Build the whole worksheet as one string."""
    out = []
    out.append("# Week 5 — reading worksheet")
    out.append("")
    # Machine-readable provenance, so later steps can report the same numbers without
    # anyone retyping them.
    out.append(f"<!-- sample_size: {len(sample)} -->")
    out.append(f"<!-- population: {population_size} -->")
    out.append(f"<!-- seed: {seed} -->")
    out.append("")
    out.append("## How this sample was drawn (the proof it was not curated)")
    out.append("")
    out.append(f"- Traces available when drawn: **{population_size}**")
    out.append(f"- Sample size requested: **{requested}**, actually drawn: **{len(sample)}**")
    out.append(f"- Random seed: **{seed}**")
    out.append(f"- Drawn at: {datetime.now().isoformat(timespec='seconds')}")
    out.append(f"- Reproduce this exact sample: "
               f"`python scripts/sample_traces.py --n {requested} --seed {seed} --force`")
    out.append("")
    out.append("Trace ids in this sample, in the order they were drawn:")
    out.append("")
    out.append("`" + ", ".join(str(t.get("trace_id", "?")) for t in sample) + "`")
    out.append("")
    out.append("## How to fill this in")
    out.append("")
    out.append("Read every block below, in order, and do not skip the ones that look fine.")
    out.append("")
    out.append("- **verdict** — `ok` if the answer is acceptable, `bad` if it is not.")
    out.append("  A refusal on a question the documents *do* answer is `bad`. So is a")
    out.append("  confident answer to something the documents never mention.")
    out.append("- **note** — for every `bad`, one honest sentence describing what actually")
    out.append("  went wrong, in your own words. Not a category. Not a fix. What you saw.")
    out.append("- **severity** — `1` mildly wrong or incomplete, `2` misleading, `3` a")
    out.append("  confident wrong answer someone could act on and be harmed by.")
    out.append("")
    out.append("**Do not write categories yet.** Fill in every note first. Grouping comes")
    out.append("next, with `python scripts/code_notes.py`, which will refuse to run until")
    out.append("the notes are done. That ordering is the whole method.")
    out.append("")
    out.append("---")
    out.append("")

    for number, trace in enumerate(sample, start=1):
        config = trace.get("config") or {}
        out.append(f"## trace {trace.get('trace_id', '?')}")
        out.append("")
        out.append(f"*sample {number} of {len(sample)} · log line {trace.get('line_no')} · "
                   f"{trace.get('ts', '')} · mode={config.get('retrieval_mode', '?')} · "
                   f"top_k={config.get('top_k', '?')} · chunk_size={config.get('chunk_size', '?')}*")
        out.append("")
        out.append(f"**Question:** {_one_line(trace.get('question', ''))}")
        out.append("")
        out.append("**Fetched:**")
        out.append("")
        out.append("```")
        out.append(_fetched_summary(trace))
        out.append("```")
        out.append("")
        out.append(f"**Answer:** {_one_line(trace.get('answer', ''))}")
        out.append("")
        out.append(f"**Refused:** {trace.get('grounded') is False}")
        out.append("")
        out.append("- verdict: ")
        out.append("- note: ")
        out.append("- severity: ")
        out.append("")
        out.append("---")
        out.append("")

    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Draw a fair sample of traces to read.")
    parser.add_argument("--n", type=int, default=20, help="how many traces to read (default 20)")
    parser.add_argument("--seed", type=int, default=42,
                        help="random seed, recorded in the worksheet so the draw is reproducible")
    parser.add_argument("--out", default=DEFAULT_OUT, help="where to write the worksheet")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing worksheet (this DELETES notes you wrote)")
    args = parser.parse_args()

    if args.n < 1:
        print(f"Error: --n must be 1 or greater, got {args.n}.")
        return 1

    traces = read_traces()
    if not traces:
        print(f"No traces yet in {settings.traces_path}")
        print("Build a population first:  python scripts/ask_batch.py")
        return 1

    # Refuse to destroy handwritten notes. This is the one irreversible thing here.
    if os.path.exists(args.out) and not args.force:
        print(f"Error: {os.path.relpath(args.out, BASE_DIR)} already exists.")
        print("It may contain notes you wrote by hand, and rewriting it would delete them.")
        print("Pass --force if you really want a fresh sample.")
        return 1

    if args.n > len(traces):
        print(f"Note: asked for {args.n} traces but only {len(traces)} exist — using all "
              f"{len(traces)}. This is a census, not a sample, so the fairness argument "
              f"does not apply. Run scripts/ask_batch.py to build a bigger population.")
        sample = list(traces)
    else:
        sample = random.Random(args.seed).sample(traces, args.n)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(_worksheet(sample, len(traces), args.seed, args.n))

    refused = sum(1 for t in sample if t.get("grounded") is False)
    print(f"Wrote {os.path.relpath(args.out, BASE_DIR)}")
    print(f"  population {len(traces)} · sampled {len(sample)} · seed {args.seed}")
    print(f"  of the sample, {refused} were refusals and {len(sample) - refused} were answers")
    print("\nNext: read every block and fill in verdict / note / severity by hand.")
    print("Then:  python scripts/code_notes.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
