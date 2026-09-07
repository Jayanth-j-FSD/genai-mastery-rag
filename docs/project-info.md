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
│   ├── TODO.md              the live checklist
│   ├── week3/  week4/  week5/  week6/   per-week notes
│
├── app/                   ← the application
│   ├── config.py            all settings (models, chunk size, top-K, paths)
│   ├── models.py            the shapes of a request and a response
│   ├── tracing.py           writes a full record of every request (for weeks 4-5)
│   ├── main.py              the FastAPI web server (endpoints)
│   └── rag/                 the pipeline — ONE FILE PER STAGE:
│       ├── loader.py          1. read files          → text
│       ├── chunker.py         2. split into pieces   → chunks
│       ├── embedder.py        3. text → vectors      → embeddings
│       ├── store.py           4. save/search vectors → Chroma
│       ├── retriever.py       5. question → top matches
│       ├── generator.py       6. matches → grounded, cited answer
│       └── pipeline.py        wires 1-4 (ingest) and 5-6 (ask) together
│
├── scripts/               ← run from the terminal
│   ├── ingest.py            build the index from data/corpus/
│   ├── ask.py               ask one question
│   └── compare_chunks.py    compare two chunk sizes (check #4, automated)
│
├── data/                  ← not code — the app's data
│   ├── corpus/              YOUR DOCUMENTS GO HERE (PDF / txt / md)
│   ├── chroma/              the saved vector index (auto-generated)
│   └── traces/              a log line per request (auto-generated)
│
└── tests/
    └── questions.md         your ~10 test questions
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
         ├─ retriever.retrieve()      embed the question, pull the top-K nearest chunks
         ├─ generator.generate_answer()
         │      build a prompt with ONLY those chunks + rules:
         │        "answer only from this, cite the source, else say I don't know"
         │      → (answer, sources, grounded)
         └─ tracing.log_trace()       append the whole request to data/traces/traces.jsonl
   ◀─ returns {answer, sources, grounded}
```

## Where each mentor check is enforced (so you can point to it)

| Check                       | Lives in                                                                           |
| --------------------------- | ---------------------------------------------------------------------------------- |
| #1 correct answer from docs | `retriever.py` (finds the right chunk) + `generator.py` (uses it)                  |
| #2 shows the source         | `generator.py` returns `sources`; `models.py` carries them to the response         |
| #3 says "I don't know"      | `generator.py` — the grounding prompt permits + requires refusal; `grounded=False` |
| #4 chunk-size experiment    | `config.py` — change `chunk_size`, re-run ingest, compare                          |

## The knobs you'll actually turn (all in `app/config.py` or `.env`)

- `chunk_size` / `chunk_overlap` — how big the pieces are. **The graded experiment.**
- `top_k` — how many chunks to retrieve per question (start 4).
- `min_relevance` — optional floor; if the best chunk is weaker than this, answer
  "I don't know" without asking the model. `0.0` = off (tune after seeing real scores).
- `llm_model` / `embed_model` — which OpenAI models to use.

## How it grows in later weeks

- **Week 4** adds an _inspection view_ over `data/traces/` and extra retrieval stages
  (hybrid search, a reranker) — new files under `app/rag/`, same pipeline shape.
- **Week 5** _reads_ `data/traces/` to rank problems — no new app code, just analysis.
- **Week 6** adds an `evals/` folder that scores the app automatically.

Because every stage is isolated and every request is traced, those additions slot in without
rewrites. That's why the structure looks the way it does.
