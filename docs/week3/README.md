# Week 3 — Build the RAG app

## The task (from the brief)
Build a mini "ask my documents" app. Load a set of real documents, let a user ask a question,
and answer using **only** those documents — with a link to the source. If the answer isn't in
the documents, it should say so instead of inventing one. Ingest your assigned document set and
**prove your chunking finds the answer**.

Same task, six topic variants (A support tickets · B recipes · C HR policy · D insurance ·
E developer docs · F legal contracts). The app is identical; only the documents differ.

## What we build this week
The full pipeline, end to end: **load → chunk → embed → store → retrieve → ground.**
See `../project-info.md` for how the files fit together.

## Definition of done — the 4 mentor checks
1. **Correct from docs** — answers a real question using the documents.
2. **Shows the source** — every answer names which document it came from.
3. **Admits ignorance** — asked something not in the docs, says "I don't know".
4. **Chunk-size experiment** — tried two chunk sizes and noticed the difference.

## Build order (see ../TODO.md for the checklist)
1. Environment: venv, install, `.env` with `OPENAI_API_KEY`, docs in `data/corpus/`.
2. Implement the six stages in `app/rag/` + tracing.
3. Wire `pipeline.ingest()` and `pipeline.answer()`.
4. CLI (`ingest.py`, `ask.py`) then the FastAPI app.
5. Prove the four checks with `tests/questions.md`.

## The chunk-size experiment (check #4), concretely
1. Ingest with `chunk_size=800, chunk_overlap=120`, ask your test questions, note results.
2. Change to `chunk_size=400, chunk_overlap=60` in `.env`, re-run `ingest.py`, ask again.
3. Write down what changed — did smaller chunks retrieve more precisely? Miss context?
   That written observation is what the mentor is looking for.

Shortcut: `python scripts/compare_chunks.py` does both sizes automatically and prints,
per question, which chunk size retrieved the right document — a ready-made observation.

## A note that pays off next week
The app logs a **complete trace** of every request to `data/traces/traces.jsonl`
(question + retrieved chunks + answer). Week 4's debugging and Week 5's error analysis both
read this file — so it's built in from day one, not bolted on later.
