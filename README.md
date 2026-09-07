# AI-Task — Ask My Documents (RAG)

A Retrieval-Augmented Generation app that answers questions **only** from a set
of documents, cites its source, and says "I don't know" when the answer isn't
there. This is the hands-on build for the GenAI course, Modules 2-3 (Weeks 3-6).

- **Week 3** — build the app (current week)
- **Week 4** — debug retrieval, prove fixes with a number
- **Week 5** — read traces, rank the real problems
- **Week 6** — evals: score every change automatically

New here? Read the docs in this order:
1. `docs/overview.md` — what we're building and why (the whole arc)
2. `docs/project-info.md` — the folder structure and how a request flows through it
3. `docs/week3/README.md` — this week's task and definition of done
4. `docs/TODO.md` — the live checklist

Stack: Python · FastAPI · OpenAI · Chroma.

## Quick start (once the code phase is done)
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
