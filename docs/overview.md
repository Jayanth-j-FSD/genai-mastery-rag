# Project Overview — Ask My Documents

## What we're building
A small app that answers a user's question **using only a set of documents you give it**,
shows **which document** each answer came from, and honestly says **"I don't know"** when the
answer isn't in those documents. That pattern is called **RAG** — Retrieval-Augmented
Generation.

## Why it exists (the business reason)
A plain AI model answers from what it read on the public internet. It has never seen *your*
company's documents, and if you ask about them it will confidently make something up. RAG
fixes that: it looks up the right documents first, then answers from them — so the answer is
grounded in real facts and is traceable to a source. This is how support bots, internal
"ask our handbook" tools, and document assistants are built.

## The arc (this one project, growing)
This same app is carried across the course weeks. Each week hardens or extends it:

| Week | Theme | What we do to the app |
|------|-------|-----------------------|
| **3** | Retrieval & RAG | **Build it** — load, chunk, embed, store, retrieve, answer-with-citation. |
| **4** | Debugging retrieval | When it's wrong, tell *why* (wrong doc vs wrong answer) and fix it, proven with a number. |
| **5** | Error analysis | Read ~20 real answers, name the recurring problems, rank them. |
| **6** | Evals | Build an automatic test so every future change gets a score, not a guess. |
| **7** | Agent loops | Build a tool-using agent by hand, and race it against a fixed workflow. |
| **8** | Agent failure modes | Judge the whole path, not just the answer; attack the agent with hidden instructions and defend it. |
| **9** | MCP | Let the agent discover tools over the standard protocol, and expose one of ours. |

[GOAL.md](GOAL.md) holds the plan, the delivery rules and the current status of each week.

The app was designed from day one to make the later weeks easy — most importantly, it **logs a
complete trace of every request** (question + what it fetched + what it answered), which is exactly
what weeks 4 and 5 need to read. Both weeks spent nothing on plumbing as a result: Week 4's
inspection view and Week 5's sampling both just read that file.

Each week is frozen as a git tag, so any week's *code* can be shown on its own: `git checkout
week-3`, then `git checkout main` to come back. (The old tags predate the free-provider support, so
running one needs a real OpenAI key and a re-ingest; see the README.) `docs/build-loop.md`
describes the process every week follows, and `docs/hardening/README.md` records what changed
after the first three tags and why.

## The pipeline (six stages)
A question flows through six steps. Each is its own file in `app/rag/`, so any one can be
swapped without touching the others.

```
INGEST (once per document set):
  load ──▶ chunk ──▶ embed ──▶ store
  read      split      turn into    save vectors
  files     into       numbers      in Chroma
            pieces

ASK (every question):
  retrieve ──▶ ground ──▶ (log trace)
  find the      write the answer
  top matches   from ONLY those, cite
                the source, or "I don't know"
```

Week 4 widened the retrieve step. It now runs two searches and merges them:

```
              ┌─ dense search  (by meaning, Week 3) ──┐
  question ──▶│                                        ├─▶ RRF merge ──▶ top matches
              └─ keyword search (BM25, exact words) ──┘
```

Set `RETRIEVAL_MODE=dense` to switch the keyword half off and get the Week 3 behaviour back,
which is how the before/after comparison is measured.

The "dense search" box itself is exact: `store.query` compares the question with every stored
vector (`DENSE_SEARCH=exact`, the default). Chroma's approximate index is still available
(`DENSE_SEARCH=ann`) but missed the right chunk on this corpus and varied run to run; see
`docs/hardening/README.md`.

## Tech stack (and why)
- **Python + FastAPI** — the course language; FastAPI gives a clean API surface (and plays to
  your backend background).
- **An OpenAI-compatible chat model** — the answer model. The `openai` SDK is pointed at Google
  Gemini's free tier (`OPENAI_BASE_URL`), so nothing needs billing; a real OpenAI key works by
  clearing that one setting. Every call goes through `app/llm.py`, which throttles to the free
  tier's per-minute limit, retries, and counts tokens.
- **A local embedding model** — all-MiniLM-L6-v2 (ONNX, 384 dimensions) on onnxruntime and
  tokenizers: free, offline, no quota. `scripts/download_model.py` fetches it once.
- **Chroma** — a local vector database, zero setup, stores the chunk vectors.
- **LangChain text-splitter + pypdf** — chunking and reading PDFs.

## Definition of done — Week 3 (this is exactly what that mentor graded)
1. Answers a real question **correctly, from the documents**.
2. Every answer **shows which document** it came from.
3. Asked something **not** in the docs, it **admits it doesn't know** (doesn't invent).
4. You tried **two chunk sizes** and can say what changed.

Nothing beyond these four was required for Week 3. See `week3/README.md` for the build steps
and `project-info.md` for how the code is laid out.

## Definition of done — Week 4
1. For a specific failure, **show which of the two kinds it is**, with evidence.
2. Make **one** change, not five.
3. Produce a **before-and-after number**, not a feeling.
4. Say which failures the change **did not** fix.

Full detail in `week4/README.md`; the deliverable itself is `week4/findings.md`.

## Definition of done — Week 5
1. Read a **fair sample** of about 20 real traces, not the good examples.
2. One **honest note per failure**, written *before* deciding on any categories.
3. Problem groups with **clear names a stranger would understand**.
4. The problems **ranked**, with a chosen target and a prediction written first.

Full detail in `week5/README.md`; the deliverable itself is `week5/taxonomy.md`. This is the
one week whose deliverable cannot be generated — the reading is the work.
