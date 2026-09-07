"""The web API (FastAPI) — the same pipeline, reachable over HTTP.

Run `uvicorn app.main:app --reload`, then open
http://127.0.0.1:8000/docs to try it in the browser. This file just exposes the
pipeline's ingest() and answer() as web endpoints.
"""
from fastapi import FastAPI, HTTPException

from app.models import AskRequest, AskResponse
from app.rag.pipeline import answer as run_answer, ingest as run_ingest

app = FastAPI(title="Ask My Documents", version="1.0.0")


@app.get("/health")           # quick "is it alive?" check
def health():
    return {"status": "ok"}


@app.post("/ingest")          # (re)build the index from data/corpus/
def ingest_endpoint():
    try:
        return run_ingest()
    except RuntimeError as exc:
        # Turn our clear error into a proper 400 response instead of a crash.
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/ask", response_model=AskResponse)   # answer a question, with sources
def ask_endpoint(req: AskRequest):
    return run_answer(req.question)
