# Project Info — the structure, and how it works

This explains **where everything lives** and **how a request travels through the code**, so
you can read the app with confidence. No prior knowledge of the codebase assumed.

## The folder structure, annotated

```
AI-Task/
├── README.md              ← how to run it
├── requirements.txt       ← the Python packages to install
├── .env.example           ← copy to .env, paste your OPENAI_API_KEY
├── .gitignore             ← keeps secrets + generated data out of git
│
├── docs/                  ← YOU ARE HERE — all project documentation
│   ├── overview.md          what & why & the 4-week arc
│   ├── project-info.md      this file: structure + how it works
│   ├── build-loop.md        the nine-step process each week follows
│   ├── TODO.md              the live checklist
│   ├── week3/  week4/  week5/  week6/   per-week notes
│
├── app/                   ← the application
│   ├── config.py            all settings (models, chunk size, top-K, mode, paths)
│   ├── models.py            the shapes of a request and a response
│   ├── tracing.py           writes + reads a full record of every request
│   ├── worksheet.py         (wk5) parses the hand-filled error-analysis notes
│   ├── main.py              the FastAPI web server (endpoints, incl. /inspect)
│   └── rag/                 the pipeline — ONE FILE PER STAGE:
│       ├── loader.py          1. read files          → text
│       ├── chunker.py         2. split into pieces   → chunks
│       ├── embedder.py        3. text → vectors      → embeddings
│       ├── store.py           4. save/search vectors → Chroma
│       ├── retriever.py       5. question → top matches (dense or hybrid)
│       ├── generator.py       6. matches → grounded, cited answer
│       ├── keyword.py         (wk4) BM25 keyword search over the same chunks
│       ├── fusion.py          (wk4) merge two ranked lists by position (RRF)
│       ├── diagnose.py        (wk4) label a failure: RETRIEVAL vs GENERATION
│       └── pipeline.py        wires 1-4 (ingest) and 5-6 (ask) together
│
├── scripts/               ← run from the terminal
│   ├── ingest.py            build the index from data/corpus/
│   ├── ask.py               ask one question
│   ├── compare_chunks.py    compare two chunk sizes (check #4, automated)
│   ├── inspect_traces.py    (wk4) question / fetched / answer, side by side
│   ├── diagnose_failures.py (wk4) label every case with evidence
│   ├── eval_retrieval.py    (wk4) hit-rate@3 before vs after, and what stayed broken
│   ├── ask_batch.py         (wk5) run a question bank so traces accumulate
│   ├── sample_traces.py     (wk5) seeded fair sample → the reading worksheet
│   ├── code_notes.py        (wk5) notes → named groups (refuses if notes are unfinished)
│   └── rank_problems.py     (wk5) rank groups by frequency x severity
│
├── data/                  ← not code — the app's data
│   ├── corpus/              YOUR DOCUMENTS GO HERE (PDF / txt / md)
│   ├── chroma/              the saved vector index (auto-generated)
│   └── traces/              a log line per request (auto-generated)
│
└── tests/
    ├── questions.md         your ~10 test questions (week 3)
    ├── eval_set.py          (wk4) the same idea, labelled so a script can score it
    └── trace_questions.txt  (wk5) ~40 questions, to build a population of real traces
```

Rule of thumb: **`app/rag/` is the brain, one stage per file. `data/` is what it reads and
writes. `scripts/` and `app/main.py` are just two doors into the same pipeline** (terminal
vs web).

## How it works — two flows

The app does exactly two things. Both run through `app/rag/pipeline.py`.

### Flow 1 — INGEST (you run this once after adding documents)

```
scripts/ingest.py
   └─▶ pipeline.ingest()
         ├─ loader.load_documents()   read every file in data/corpus/  → text + source name
         ├─ chunker.chunk_documents() cut each doc into ~800-char pieces (config.chunk_size)
         ├─ embedder.embed_texts()    send chunks to OpenAI → a vector per chunk
         └─ store.add_chunks()        save vectors + text + source into Chroma (data/chroma/)
```

After this, your documents are searchable. You only re-run it when the documents change —
**or when you change the chunk size** (that's the Week 3 experiment).

### Flow 2 — ASK (runs on every question)

```
scripts/ask.py "question"   OR   POST /ask {question}
   └─▶ pipeline.answer(question)
         ├─ retriever.retrieve_for_mode()   pick the search strategy, then:
         │    ├─ dense  → retrieve()        embed the question, take the nearest chunks
         │    └─ hybrid → retrieve_hybrid() dense + keyword.search(), merged by fusion.fuse()
         ├─ generator.generate_answer()
         │      build a prompt with ONLY those chunks + rules:
         │        "answer only from this, cite the source, else say I don't know"
         │      → (answer, sources, grounded)
         └─ tracing.log_trace()       append the whole request to data/traces/traces.jsonl
   ◀─ returns {answer, sources, grounded, retrieval_mode}
```

### Flow 3 — INSPECT (Week 4, reads the trace log, changes nothing)

```
scripts/inspect_traces.py   OR   GET /inspect
   └─▶ tracing.read_traces()   parse data/traces/traces.jsonl, skipping bad lines
         └─ print question / fetched chunks (with which search found each) / answer
```

### Flow 4 — ANALYSE (Week 5, reads the trace log, changes nothing)

```
scripts/ask_batch.py         run ~40 questions through Flow 2, so traces accumulate
   └─▶ scripts/sample_traces.py   seeded random sample → docs/week5/worksheet.md
         └─▶ YOU read all 20 and write verdict / note / severity by hand
               └─▶ scripts/code_notes.py    validates, then → coded-notes.md (+ your codes)
                     └─▶ scripts/rank_problems.py   frequency x severity → ranked-problems.md
```

Each arrow is a gate: the next script refuses to run until the previous step is genuinely
finished. `app/worksheet.py` is the shared parser for the two hand-filled files.

## Where each mentor check is enforced (so you can point to it)

Week 3:

| Check                       | Lives in                                                                           |
| --------------------------- | ---------------------------------------------------------------------------------- |
| #1 correct answer from docs | `retriever.py` (finds the right chunk) + `generator.py` (uses it)                  |
| #2 shows the source         | `generator.py` returns `sources`; `models.py` carries them to the response         |
| #3 says "I don't know"      | `generator.py` — the grounding prompt permits + requires refusal; `grounded=False` |
| #4 chunk-size experiment    | `config.py` — change `chunk_size`, re-run ingest, compare                          |

Week 4:

| Check                        | Lives in                                                                       |
| ---------------------------- | ------------------------------------------------------------------------------ |
| #1 which kind of failure     | `rag/diagnose.py` → `classify()`; run it with `scripts/diagnose_failures.py`   |
| #2 one change, not five      | `rag/keyword.py` + `rag/fusion.py` are the whole change; `week4/CHANGES.md` lists what was refused |
| #3 before-and-after number   | `scripts/eval_retrieval.py` → hit-rate@k and MRR across both modes            |
| #4 what stayed broken        | the same script's `STILL BROKEN` / `REGRESSED` lists                          |

## The knobs you'll actually turn (all in `app/config.py` or `.env`)

- `chunk_size` / `chunk_overlap` — how big the pieces are. **Week 3's graded experiment.**
- `top_k` — how many chunks to retrieve per question (start 4).
- `min_relevance` — optional floor; if the best chunk is weaker than this, answer
  "I don't know" without asking the model. `0.0` = off (tune after seeing real scores).
- `llm_model` / `embed_model` — which OpenAI models to use.
- `retrieval_mode` — `dense` (Week 3) or `hybrid` (Week 4). **Week 4's graded experiment.**
- `hybrid_candidates` / `rrf_k` — how many candidates each search contributes, and how
  sharply the merge favours top positions. Turn `hybrid_candidates` down if keyword noise
  starts outranking good semantic hits.
- `bm25_k1` / `bm25_b` — BM25's term-saturation and length-penalty knobs.
- `eval_k` — the `k` in hit-rate@k that the eval script highlights (3, per the brief).

## How it grows in later weeks

- **Week 4** (done) added an _inspection view_ over `data/traces/` and a second retrieval
  strategy — new files under `app/rag/`, same pipeline shape, nothing rewritten.
- **Week 5** _reads_ `data/traces/` to rank problems — no new app code, just analysis tools.
- **Week 6** adds an `evals/` folder that scores the app automatically.

Because every stage is isolated and every request is traced, those additions slot in without
rewrites. That's why the structure looks the way it does. Week 4 proved it: the inspection
view needed no change to any existing stage, only a reader for the log that was already there.
