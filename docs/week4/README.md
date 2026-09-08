# Week 4 — Debugging Retrieval

## The task (from the brief)
The app from Week 3 works, but it is sometimes wrong. "Wrong sometimes" is useless to fix.
This week separates the two kinds of wrong, because they need completely different fixes:

- **The app fetched the wrong document.** A smarter answer model changes nothing here. You
  would pay more and fix nothing. The search is the problem.
- **The app fetched the right document and still answered badly.** The facts were on the
  table and the model mishandled them. The prompt or the chunking is the problem.

Then: take the failing questions, label each one, make **one** improvement, and prove it
helped with a before-and-after number.

## Definition of done — the 4 mentor checks
1. **Can you show, for a specific failure, which of the two kinds it is — with evidence?**
2. **Did you make one change (not five), so you know what actually helped?**
3. **Is there a before-and-after number, not just "it feels better"?**
4. **Did you notice which failures your change did NOT fix?**

## The one change: hybrid retrieval
Week 3 searched by meaning only (a "dense" search). That is strong on paraphrases and weak on
exact strings, because a code like `ERR-4032` carries almost no meaning to embed. This week
adds a **keyword search (BM25)** alongside it and merges the two ranked lists with
**Reciprocal Rank Fusion (RRF)**.

That is deliberately the *only* change. Reranking, query rewriting, HyDE and MMR were all
studied and consciously left out — with four changes at once, the before/after number would
not tell you which one earned it. `CHANGES.md` records the reasoning per technique.

Both strategies stay switchable, which is what makes the measurement fair:

```bash
RETRIEVAL_MODE=dense    # exactly the Week 3 search
RETRIEVAL_MODE=hybrid   # this week's change (the default now)
```

## How to run this week's work

Everything below assumes the Week 3 setup is done (venv, `pip install -r requirements.txt`,
`.env` with your key) and the index is built with `python scripts/ingest.py`.

**1. Look at what the app is actually doing.** The inspection view shows question, fetched
chunks, and answer side by side. Every chunk says which search found it and at what rank.

```bash
python scripts/inspect_traces.py --last 20
python scripts/inspect_traces.py --ungrounded        # only the refusals
python scripts/inspect_traces.py --trace <id>        # one request, full chunk text
```

The same view runs in the browser at `http://127.0.0.1:8000/inspect` while
`uvicorn app.main:app --reload` is running.

**2. Label the failures (check #1).** Diagnose the app *as it was* before the change:

```bash
python scripts/diagnose_failures.py --mode dense --save
```

Each case prints as `[RETRIEVAL]`, `[GENERATION]` or `[PASS]` with the evidence underneath:
what was fetched, at what rank, which search found it, and what the app answered. The report
is written to `failure-labels-dense.md` next to this file. Re-run with `--mode hybrid --save`
after the change to see which labels moved. Add `--no-model` for a free retrieval-only pass.

**3. Measure before and after (checks #3 and #4).**

```bash
python scripts/eval_retrieval.py --save
```

This asks every labelled question under both searches and prints hit-rate@1, @3 and @5 plus
MRR for each, with the change. It then lists by name the questions that were **fixed**, the
ones **still broken**, and any it **regressed**. Output lands in `eval-results.md`.

Only the search runs, never the answer model, so it costs one small embedding call per
question per mode.

**4. Write it up.** Put the numbers and the labels into `findings.md`. That file is the
deliverable the mentor reads.

## Where the answers to the four checks live

| Check | Where to point |
|-------|----------------|
| #1 evidence per failure | `app/rag/diagnose.py`, run via `scripts/diagnose_failures.py` |
| #2 one change | `app/rag/keyword.py` + `app/rag/fusion.py`; the switch in `app/config.py` |
| #3 before/after number | `scripts/eval_retrieval.py`, recorded in `findings.md` |
| #4 what stayed broken | the "NOT fixed by the change" section of the same script |

## What Week 3 promised and this week used
Week 3 logged a complete trace of every request from day one. Week 4 did not have to add
logging or re-run anything to get an inspection view; it just had to read the file. That is
the payoff for building tracing in early rather than bolting it on.
