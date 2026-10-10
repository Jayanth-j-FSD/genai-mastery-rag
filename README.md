# AI-Task: Ask My Documents (RAG)

A Retrieval-Augmented Generation app that answers questions **only** from a set of documents,
cites its source, and says "I don't know" when the answer isn't there. It is the hands-on build for
a GenAI course: one app that grows week by week, each week on its own branch and tag.

Track C (HR policy). Stack: Python 3.12, FastAPI, Chroma, a local ONNX embedding model, and an
OpenAI-compatible chat model (Google Gemini's free tier by default, so nothing here needs billing).

- **Week 3**: build the app
- **Week 4**: debug retrieval, prove one change with a number
- **Week 5**: read real traces, name and rank the problems
- **Week 6**: evals you can run with one command
- **Week 7**: an agent loop built by hand, raced against a fixed workflow
- **Weeks 8 and later**: agent failure modes and prompt injection, then MCP. See [docs/GOAL.md](docs/GOAL.md)
  for the plan and status.

## What you need

- **Python 3.12** (verified on 3.12.10). On Windows, call the venv's Python directly
  (`.\.venv\Scripts\python.exe`): a bare `python` can hit the Microsoft Store stub.
- A **free Gemini API key** from <https://aistudio.google.com> (Create API key, no billing),
  or an OpenAI key. See `.env.example` for both setups.
- About 100 MB of disk for the offline embedding model, downloaded once.

## Quick start

PowerShell. On macOS/Linux use `python3.12 -m venv .venv` and `.venv/bin/python`; Git Bash on Windows uses
`.venv/Scripts/python.exe`.

```powershell
py -3.12 -m venv .venv                                  # the Windows launcher: a bare `python` can be the Store stub
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env                                  # then paste your key into OPENAI_API_KEY
.\.venv\Scripts\python.exe scripts\download_model.py    # the offline embedding model, once
.\.venv\Scripts\python.exe scripts\ingest.py            # build the index from data/corpus/
.\.venv\Scripts\python.exe scripts\ask.py "How many weeks of paid parental leave are available?"
```

Or run the web API and open <http://127.0.0.1:8000/docs>:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

`/ask` answers a question, `/ingest` rebuilds the index, `/inspect` shows every past request next to
the chunks it fetched.

Documents live in `data/corpus/` (`.md`, `.txt`, `.pdf`). After changing them or `CHUNK_SIZE`,
run `scripts\ingest.py` again.

## Check that nothing is broken

```powershell
.\.venv\Scripts\python.exe scripts\check_all.py
```

It compiles every file, imports every module and script, builds every script's argument parser and
runs the offline unit tests (a fake embedder and a stub model, so no network and no quota). It exits
non-zero if anything fails, and every week must pass it before it is tagged.

## Commands by week

| Week | Command | What it does |
|---|---|---|
| 3 | `scripts\ingest.py`, `scripts\ask.py "..."` | build the index, ask one question |
| 3 | `scripts\compare_chunks.py --save` | the two-chunk-size experiment (check #4), numbers only |
| 4 | `scripts\inspect_traces.py --last 20` | question / fetched chunks / answer, side by side |
| 4 | `scripts\diagnose_failures.py --mode dense --save` | label each failure RETRIEVAL or GENERATION, with evidence |
| 4 | `scripts\eval_retrieval.py --save` | hit-rate@k and MRR, dense vs hybrid |
| 5 | `scripts\ask_batch.py` | run the question bank so real traces accumulate |
| 5 | `scripts\sample_traces.py --n 20` | seeded fair sample into a reading worksheet |
| 5 | *(you read and write the notes)* | `docs\week5\worksheet.md` |
| 5 | `scripts\code_notes.py`, `scripts\rank_problems.py --save` | notes to named groups to a ranking |
| 6 | `scripts\run_evals.py` | the whole eval set (41 cases) with one command: rule checks plus an AI judge, saved per run |
| 6 | `scripts\compare_evals.py baseline after` | before and after, per problem type, naming the cases that changed |
| 6 | `scripts\screen_retrieval.py` | free screen of retrieval settings (no model calls) |
| 6 | `scripts\make_judge_sheet.py`, `scripts\validate_judge.py` | a blind sheet you grade by hand, then how far the judge agrees with you |
| 6 | `scripts\make_regressions.py` | turn your Week 5 failures into permanent test cases |
| 6 | `scripts\list_runs.py` | every saved eval run in one table |
| 7 | `scripts\run_agent.py "..."` | the agent loop with every step printed (`--workflow` for the fixed recipe) |
| 7 | `scripts\race_agent.py` | race the agent against the fixed workflow: reliability, cost, speed |
| hardening | `scripts\compare_ann_exact.py` | how often Chroma's approximate search disagrees with exact search |

The Week 5 reading is deliberately not automated: it is the part of the course that cannot be.
Each Week 5 script refuses to run until the previous step is genuinely finished.

## The settings that matter (`.env`)

| Setting | Default | Meaning |
|---|---|---|
| `RETRIEVAL_MODE` | `hybrid` in code, `dense` in `.env.example` | `dense` is Week 3's search, `hybrid` adds Week 4's keyword search |
| `DENSE_SEARCH` | `exact` | `exact` compares with every vector; `ann` is Chroma's approximate index (see below) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 800 / 120 | how documents are cut up |
| `TOP_K` | 4 | chunks given to the answer model |
| `LLM_RPM` | 0 | chat requests per minute allowed (set below your provider's limit; the app waits) |
| `EMBED_PROVIDER` | `openai` in code, `local` in `.env.example` | where embeddings come from; changing it needs a re-ingest |

All settings, with their meaning, are in `app/config.py`. A bad value fails at startup with a clear message.

## Things worth knowing

- **Why search is exact.** Chroma's approximate index (HNSW) returned the wrong top chunk for a
  large share of questions on this corpus, and differently on every run. The handbook contains one
  chunk repeated 136 times and another 108 times, which is the likely cause (not verified; the fix does
  not depend on it). Exact search compares the
  question with every stored vector (432 today) in milliseconds and never varies. `scripts\compare_ann_exact.py`
  shows the difference on your machine. Details: [docs/hardening/README.md](docs/hardening/README.md).
- **Free-tier limits are per model.** Measured on Gemini's free tier: the flagship alias
  (`gemini-flash-latest`) allowed 5 requests a minute and a hard daily cap near 20, while the lite
  models took 14 back to back. `.env.example` therefore uses `gemini-flash-lite-latest`. The outputs
  committed under `docs/` were produced with the explicit name `gemini-3.5-flash-lite` (an alias moves over
  time), so set `LLM_MODEL` to that exact name to replay them. `app/llm.py`
  throttles to `LLM_RPM`, retries, and stops with a clear message when a daily quota is used up.
- **The old tags.** `week-3`, `week-4` and `week-5` are the code exactly as built. They predate the
  free-provider support, so running one needs a real OpenAI key and a re-ingest. To see a week's
  *behaviour* on the current code, set `RETRIEVAL_MODE=dense` (Week 3) or `hybrid` (Week 4).
- **An empty index** now says "run scripts\ingest.py" instead of answering "I don't know", which
  would be indistinguishable from a correct refusal.

## Documentation, in reading order

1. [docs/GOAL.md](docs/GOAL.md): the goal, the delivery rules (branches, tags, review) and the status
2. [docs/overview.md](docs/overview.md): what the app is and the week-by-week arc
3. [docs/project-info.md](docs/project-info.md): the folder layout and how a request flows
4. [docs/build-loop.md](docs/build-loop.md): the process every week follows
5. [docs/hardening/README.md](docs/hardening/README.md): what changed since the three tags, and why
6. [docs/TODO.md](docs/TODO.md): the live checklist

## Secrets

`.env` is gitignored and must stay that way. Never paste a key into a file that is committed, a log
or a test.
