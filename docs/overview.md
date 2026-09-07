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

## The four-week arc (this one project, growing)
This same app is carried across four course weeks. Each week hardens it:

| Week | Theme | What we do to the app |
|------|-------|-----------------------|
| **3** | Retrieval & RAG | **Build it** — load, chunk, embed, store, retrieve, answer-with-citation. |
| **4** | Debugging retrieval | When it's wrong, tell *why* (wrong doc vs wrong answer) and fix it, proven with a number. |
| **5** | Error analysis | Read ~20 real answers, name the recurring problems, rank them. |
| **6** | Evals | Build an automatic test so every future change gets a score, not a guess. |

We're on **Week 3**. The app is designed from day one to make weeks 4-6 easy — most importantly,
it **logs a complete trace of every request** (question + what it fetched + what it answered),
which is exactly what weeks 4 and 5 need to read.

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

## Tech stack (and why)
- **Python + FastAPI** — the course language; FastAPI gives a clean API surface (and plays to
  your backend background).
- **OpenAI API** — embeddings (`text-embedding-3-small`) and the answer model (`gpt-4o-mini`).
  Simplest reliable start; both are swappable in `app/config.py`.
- **Chroma** — a local vector database, zero setup, stores the chunk vectors.
- **LangChain text-splitter + pypdf** — chunking and reading PDFs.

## Definition of done (this is exactly what the mentor grades)
1. Answers a real question **correctly, from the documents**.
2. Every answer **shows which document** it came from.
3. Asked something **not** in the docs, it **admits it doesn't know** (doesn't invent).
4. You tried **two chunk sizes** and can say what changed.

Nothing beyond these four is required for Week 3. See `week3/README.md` for the build steps
and `project-info.md` for how the code is laid out.
