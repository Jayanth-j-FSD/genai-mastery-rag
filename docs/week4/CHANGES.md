# Week 4 — what changed, and why

> **Erratum (2026-10-11).** This page is kept as written, but three statements below are no longer
> true. (1) "Has not been executed" and "no Python and no API key" (see "Status, stated honestly"):
> the scripts have since been run, and their generated output is in `docs/week4/eval-results.md`
> and `docs/week4/failure-labels-dense.md`. (2) "`tests/eval_set.py`: 18 labelled questions": the
> corpus changed after this was written, so the set was rewritten (now 32 cases); see the mapping
> at the top of `tests/eval_set.py`. (3) "`git checkout week-3` still runs the Week 3 app": it shows
> the Week 3 *code*, but running it needs a real OpenAI key and a re-ingest. Everything is
> explained in [../hardening/README.md](../hardening/README.md).

The one-page answer to "what did you actually do this week?". Week 3's code and docs were
not rewritten; everything here is either a new file or an additive change to an existing one.

## New files

| File | What it does |
|------|--------------|
| `app/rag/keyword.py` | BM25 keyword search over the same chunks the vector store holds. Written out longhand (about forty lines of arithmetic) rather than pulling in a package, so the scoring is readable. Includes a tokenizer that keeps `err-4032` intact *and* indexes its parts. |
| `app/rag/fusion.py` | Reciprocal Rank Fusion. Merges two ranked lists by position, not score, because a cosine similarity (0 to 1) and a BM25 score (0 to ~15) cannot be averaged meaningfully. |
| `app/rag/diagnose.py` | Sorts one labelled question into `RETRIEVAL`, `GENERATION` or `PASS` and returns the evidence that proves it. |
| `tests/eval_set.py` | 18 labelled questions: 14 answerable from the corpus, 4 deliberately absent. Each records its expected document(s), an accepted answer phrase, and a written prediction about which search should win it. |
| `scripts/eval_retrieval.py` | The before/after measurement: hit-rate@1/@3/@5 and MRR for both searches, plus the fixed / still-broken / regressed lists. |
| `scripts/diagnose_failures.py` | Runs the classifier over the whole eval set and prints the evidence per case. |
| `scripts/inspect_traces.py` | The inspection view in the terminal: question, fetched chunks, answer. |

## Changed files

| File | Change | Week 3 behaviour |
|------|--------|------------------|
| `app/config.py` | Added `retrieval_mode`, `hybrid_candidates`, `rrf_k`, `bm25_k1`, `bm25_b`, `eval_k`. A validator rejects an unknown `retrieval_mode` at startup instead of searching wrongly. | Unchanged. `RETRIEVAL_MODE=dense` reproduces Week 3 exactly. |
| `app/rag/retriever.py` | `retrieve()` is still the dense search and still means what its docstring says. Added `retrieve_hybrid()` and `retrieve_for_mode()` beside it. | Preserved. The three original keys (`text`, `source`, `score`) keep their meanings; `score` is a cosine similarity in **both** modes. |
| `app/rag/store.py` | Added `count_chunks()`, `get_all_chunks()`, `get_embeddings()`. | Unchanged. |
| `app/rag/pipeline.py` | `answer()` takes an optional `mode` and returns an extra `retrieval_mode` key. `ingest()` now invalidates the keyword index. | Preserved. The original three result keys are untouched. |
| `app/tracing.py` | Each traced chunk now records which search found it and at what rank; the trace carries `trace_id` and `retrieval_mode`. Added `read_traces()`. | Additive. Old trace lines still parse — the new fields simply read as absent. |
| `app/models.py` | `AskRequest.mode` (optional, validated); `AskResponse.retrieval_mode`. | Additive. |
| `app/main.py` | Added `GET /inspect` (a plain HTML side-by-side view). `/ask` passes `mode` through and returns a 400 instead of a 500 when the API key is missing. `/health` reports the active mode. | Preserved. |
| `.env.example` | Documented the six new settings. | Unchanged. |

Deliberately **not** touched: `scripts/compare_chunks.py` still calls `retrieve()`, so the
Week 3 chunk-size experiment stays reproducible forever rather than shifting under a new
retrieval strategy.

## Why `score` is still a cosine similarity in hybrid mode

A chunk that only keyword search found has no cosine score from the vector query. Reporting
its BM25 score in the same field would have silently broken two things: the `min_relevance`
floor (which compares against `score`) and the numbers shown next to each cited source.

So `retrieve_hybrid()` reads that chunk's stored embedding back out and computes the cosine
itself. Ranking is by fused position; the reported `score` stays one comparable number. If
the embedding read fails, it degrades to `0.0` with a printed warning rather than failing
the answer, because a score is presentation detail.

## The "one change" argument

The brief asks for one improvement and the mentor explicitly checks *"did they make one
change (not five)?"*. Four simultaneous changes would produce a number that proves nothing
about which one worked. So exactly one landed, and the rest were studied and written down:

| Technique | Studied | Why it is not in this week's diff |
|-----------|---------|-----------------------------------|
| **Hybrid search (BM25 + RRF)** | yes | **This is the change.** It targets the retrieval kind of failure, which is the kind a better answer model cannot fix, and it needs no new API key and no model download. |
| Cross-encoder reranking (Cohere Rerank, BGE) | yes | Needs either a second paid API or a local model download. It also reorders *within* the candidates the search already found, so it cannot rescue a document that was never retrieved — the failure mode most common here. Reranking after hybrid is the natural next step, not a substitute. |
| Query rewriting | yes | Adds an LLM call before every search, so it changes cost, latency and retrieval at once. Harder to attribute, and it would have muddied this week's number. |
| HyDE | yes | Same objection as query rewriting, plus it generates a hypothetical answer that can invent vocabulary the corpus does not use. |
| MMR (diversity) | yes | Solves near-duplicate results. Not this corpus's problem: six short, distinct documents. Would add a knob with nothing to fix. |

## Requirement to code, check by check

| Mentor check | Satisfied by | How to demonstrate it |
|---|---|---|
| #1 Show which kind a specific failure is, with evidence | `app/rag/diagnose.py` → `classify()` returns `kind`, `why`, `expected_rank` and a per-chunk `retrieved` list | `python scripts/diagnose_failures.py --mode dense --save`, then read one `[RETRIEVAL]` block aloud |
| #2 One change, not five | `app/rag/keyword.py` + `app/rag/fusion.py` are the only new retrieval behaviour; the table above records what was refused | `git diff week-3..week-4 --stat`, and the deferred-techniques table |
| #3 A before-and-after number | `scripts/eval_retrieval.py` → `_hit_rate()` and `_mrr()` over both modes | `python scripts/eval_retrieval.py --save`, then `findings.md` |
| #4 Which failures the change did NOT fix | the same script's `STILL BROKEN` and `REGRESSED` sections, from `_verdict()` | the "NOT fixed by the change" block in the output |

## The review pass — what it caught

The code was read line by line after being written, against the brief rather than against
itself. These are the defects that pass found and fixed, recorded because "I reviewed it"
means nothing without saying what the review actually turned up:

| Found | Why it mattered |
|---|---|
| A script named `scripts/inspect.py` | Python puts a script's own directory first on `sys.path`, so it would have shadowed the standard-library `inspect` module that chromadb and pydantic both import. Renamed to `inspect_traces.py` before it was ever run. |
| Hybrid mode reported a BM25 score in the `score` field | Would have silently broken the `min_relevance` floor (which compares against `score`) and shown incomparable numbers next to cited sources. Now a keyword-only chunk has its cosine computed from its stored embedding. |
| `_prediction_held()` used `verdict in (...) is False` | Python chains those comparisons, so the expression evaluated to nonsense. Replaced with an explicit lookup that also distinguishes "held" from "dense already found it". |
| `hit-rate@k` capped at 5 while `EVAL_K` could be set higher | Setting `EVAL_K=10` would have retrieved only 5 chunks and reported the misses as real. The reported depths now always include `eval_k`. |
| `"not"` as an accepted answer phrase | A three-letter substring matches "cannot", "nothing", "another" — it would have passed almost any answer. Replaced with specific phrases. |
| A keyword-index build failure crashed the answer | Keyword search is an enhancement; it now degrades to meaning-only with a warning instead of failing the request. Same for the embedding read used for scoring. |
| `bm25_b` outside 0..1 could divide by zero | Added range validators for `bm25_b`, `bm25_k1`, `rrf_k`, `top_k`, `hybrid_candidates` and `eval_k`, so a bad `.env` fails loudly at startup rather than scoring strangely. |
| An empty question reached the embeddings API | `retrieve()` and `retrieve_hybrid()` now return `[]` for a blank question instead of sending it. |
| An unused import and a stray f-string | Removed in the clean pass. |

Unhandled deliberately: an unexpected exception inside the two evaluation scripts prints its
type and a "did you ingest and set your key?" hint rather than a traceback, but it is not
swallowed silently.

## Status, stated honestly

The code is written and reviewed but **has not been executed** — this machine has no Python
and no API key. Every number in `findings.md` is therefore an empty cell with the command
that fills it. Nothing in this folder claims a measurement that has not been taken.

`git checkout week-3` still runs the Week 3 app exactly as the Week 3 mentor saw it.
