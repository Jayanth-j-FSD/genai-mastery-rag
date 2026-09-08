# TODO — the live checklist

Status legend:  `[ ]` not started · `[~]` in progress · `[x]` done

## Phase 0 — Scaffolding (done)
- [x] Create AI-Task folder + structure
- [x] Scaffold app/ modules, scripts, config, models
- [x] Write docs (overview, project-info, week3, this file)
- [x] requirements.txt, .env.example, .gitignore

## Phase 1 — Code (written + reviewed + hardened; NOT yet run)
- [x] `loader.py` — read PDF/txt/md from corpus into text + source
- [x] `chunker.py` — recursive splitter using config chunk_size/overlap
- [x] `embedder.py` — OpenAI embeddings, batched; same model both sides
- [x] `store.py` — persistent Chroma collection; reset + add + query (cosine)
- [x] `retriever.py` — embed question, return top-K chunks with score + source
- [x] `generator.py` — grounding prompt: answer-only-from-context, cite, "I don't know"
- [x] `tracing.py` — append complete trace (question + chunks + answer + config) to JSONL
- [x] `pipeline.py` — wire ingest() and answer()
- [x] `scripts/ingest.py`, `scripts/ask.py`, `app/main.py` (FastAPI)
- [x] Sample corpus (Northwind Labs) + tests/questions.md

> NOTE: code is written and reviewed but has NOT been executed — this machine has
> no Python installed and no API key in-session. Verification is Phase 3.

## Phase 1b — Smart enhancements (done; make the four checks shine)
- [x] Precise citations — show only the documents the model actually cited (check #2)
- [x] Injection-aware prompt — treat retrieved docs as data, not commands (Week 2 applied)
- [x] `scripts/compare_chunks.py` — automated two-chunk-size comparison (check #4)
- [x] `min_relevance` floor — optional weak-match guard, off by default (check #3)
- [x] Per-file chunk counts printed on ingest ("prove your chunking")
- [x] Friendly CLI errors for missing key / empty corpus

## Phase 2 — Environment (you — required before anything runs)
- [ ] **Install Python 3.11+** (not currently on this machine) — python.org, tick "Add to PATH"
- [ ] `cd` into AI-Task, then `python -m venv .venv` and activate it
- [ ] `pip install -r requirements.txt`
- [ ] `cp .env.example .env` and paste your real `OPENAI_API_KEY`

## Phase 3 — Run & verify the 4 mentor checks (definition of done)
- [ ] `python scripts/ingest.py` — builds the index (prints doc/chunk counts)
- [ ] #1 `python scripts/ask.py "how many leave days carry over?"` → correct answer from docs
- [ ] #2 answer shows the source document (annual-leave.md)
- [ ] #3 `python scripts/ask.py "what is the parental leave policy?"` → "I don't know"
- [ ] #4 change CHUNK_SIZE in .env (800→400), re-ingest, re-ask, record the difference
- [ ] (optional) `uvicorn app.main:app --reload` and try /ask at /docs

## Phase 4 — Week 4, debugging retrieval (code written + reviewed; NOT yet run)
- [x] `tests/eval_set.py` — 18 labelled questions (14 in-corpus, 4 deliberately absent)
- [x] `app/rag/keyword.py` — BM25 keyword search, written longhand, no new dependency
- [x] `app/rag/fusion.py` — Reciprocal Rank Fusion over the two ranked lists
- [x] `app/rag/retriever.py` — `retrieve_hybrid()` + `retrieve_for_mode()`; `retrieve()` unchanged
- [x] `app/rag/diagnose.py` — classify a failure as RETRIEVAL vs GENERATION, with evidence
- [x] `scripts/inspect_traces.py` + `GET /inspect` — the side-by-side inspection view
- [x] `scripts/diagnose_failures.py` — label every case, print the evidence (check #1)
- [x] `scripts/eval_retrieval.py` — hit-rate@1/@3/@5 + MRR, both modes, and the deltas (checks #3, #4)
- [x] `docs/week4/` — README (task) · CHANGES (what changed) · findings (the deliverable)
- [x] Prediction written down BEFORE measuring (`docs/week4/findings.md` section 1)

## Phase 5 — Week 4 run & verify (you — needs Python + API key)
- [ ] `python scripts/ingest.py` — rebuild the index
- [ ] #1 `python scripts/diagnose_failures.py --mode dense --save` → every case labelled with evidence
- [ ] #3 `python scripts/eval_retrieval.py --save` → hit-rate@3 before vs after
- [ ] #4 read the "NOT fixed by the change" list and record it in `findings.md`
- [ ] #2 nothing to run — the single change is the diff itself (`git diff week-3..week-4 --stat`)
- [ ] Fill in `docs/week4/findings.md` sections 2 to 6
- [ ] (optional) `uvicorn app.main:app --reload` then open `/inspect` in the browser

## Later weeks (not started)
- [ ] Week 5 — read ~20 traces, open-code, ranked taxonomy
- [ ] Week 6 — one-command eval set, validated LLM judge, RAGAS, before/after deltas

## Open / waiting on
- [ ] Real track (A-F) document pack — using sample docs (Northwind Labs) until it arrives
- [x] Project location — settled; this folder is the git repo root
