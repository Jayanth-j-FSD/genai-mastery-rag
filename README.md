# AI-Task — Ask My Documents (RAG)

A Retrieval-Augmented Generation app that answers questions **only** from a set
of documents, cites its source, and says "I don't know" when the answer isn't
there. This is the hands-on build for the GenAI course, Modules 2-3 (Weeks 3-6).

- **Week 3** — build the app
- **Week 4** — debug retrieval, prove the fix with a number
- **Week 5** — read traces, rank the real problems (current week)
- **Week 6** — evals: score every change automatically

Each week is frozen as a git tag, so any week can be shown on its own:

```bash
git checkout week-3      # the app exactly as the Week 3 mentor saw it
git checkout main        # back to the latest
```

New here? Read the docs in this order:
1. `docs/overview.md` — what we're building and why (the whole arc)
2. `docs/project-info.md` — the folder structure and how a request flows through it
3. `docs/build-loop.md` — the process each week follows
4. `docs/week5/README.md` — this week's task and definition of done
5. `docs/TODO.md` — the live checklist

Stack: Python · FastAPI · OpenAI · Chroma. No extra dependency was added for Week 4.

## Quick start
```bash
python -m venv .venv
source .venv/Scripts/activate          # Windows Git Bash
pip install -r requirements.txt
cp .env.example .env                    # then paste your OPENAI_API_KEY
# put documents in data/corpus/, then:
python scripts/ingest.py               # build the index
python scripts/ask.py "your question"  # ask from the terminal
uvicorn app.main:app --reload          # or run the API at http://127.0.0.1:8000/docs
```

## Week 4 commands
```bash
python scripts/inspect_traces.py --last 20              # question / fetched / answer
python scripts/diagnose_failures.py --mode dense --save # label failures with evidence
python scripts/eval_retrieval.py --save                 # hit-rate@3 before vs after
```

Then open `http://127.0.0.1:8000/inspect` for the same view in the browser, and fill in
`docs/week4/findings.md`.

## Week 5 commands
```bash
python scripts/ask_batch.py                 # build a population of real traces
python scripts/sample_traces.py --n 20      # seeded fair sample -> docs/week5/worksheet.md
#   then READ all 20 and write verdict / note / severity by hand
python scripts/code_notes.py                # validates the notes, then -> coded-notes.md
#   then add one group name per failure
python scripts/rank_problems.py --save      # frequency x severity ranking
```

Each step refuses to run until the previous one is genuinely finished. The reading itself is
not automated, and is not meant to be — see `docs/week5/README.md`.

Switch the retrieval strategy in `.env` at any time:

```bash
RETRIEVAL_MODE=dense    # meaning-only search (Week 3)
RETRIEVAL_MODE=hybrid   # meaning + keyword search, merged with RRF (Week 4)
```
