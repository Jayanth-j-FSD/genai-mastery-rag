"""The web API (FastAPI) — the same pipeline, reachable over HTTP.

Run `uvicorn app.main:app --reload`, then open
http://127.0.0.1:8000/docs to try it in the browser. This file just exposes the
pipeline's ingest() and answer() as web endpoints.

Week 4 adds /inspect — a plain HTML page showing, for recent requests, the question,
the chunks that were fetched, and the final answer side by side.
"""
from html import escape

import openai
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from app import llm, observability
from app.config import settings
from app.models import AskRequest, AskResponse
from app.rag.pipeline import answer as run_answer, ingest as run_ingest
from app.tracing import read_traces

app = FastAPI(title="Ask My Documents", version="1.1.0")


def _id_header():
    """The X-Request-ID header for the request this thread just answered or failed, or None when it made no log (an empty question)."""
    request_id = observability.last_request_id()
    return {"X-Request-ID": request_id} if request_id else None


def _run(action, *args):
    """Run a pipeline action and turn its expected failures into proper HTTP errors.

    Without this a rate-limited or rejected AI call would surface as a bare "500 Internal
    Server Error" with nothing to act on. Week 11: an error carries the id of the request that failed, so a support
    person can find it in errors.jsonl.
    """
    try:
        return action(*args)
    except llm.QuotaExhausted as exc:           # a RuntimeError subclass, so it must come first
        raise HTTPException(status_code=429, detail=str(exc), headers=_id_header())
    except RuntimeError as exc:                 # e.g. no key, no documents, nothing indexed yet
        raise HTTPException(status_code=400, detail=str(exc), headers=_id_header())
    except openai.RateLimitError:
        raise HTTPException(status_code=429, detail="The AI provider's rate limit was hit. "
                                                    "Wait a minute and try again.", headers=_id_header())
    except (openai.APIStatusError, openai.APIConnectionError) as exc:
        raise HTTPException(status_code=502, detail=f"The AI provider call failed "
                                                    f"({type(exc).__name__}). Check the key, model and network.", headers=_id_header())


@app.get("/health")           # quick "is it alive?" check
def health():
    return {"status": "ok", "retrieval_mode": settings.retrieval_mode}


@app.post("/ingest")          # (re)build the index from data/corpus/
def ingest_endpoint():
    return _run(run_ingest)


@app.post("/ask", response_model=AskResponse)   # answer a question, with sources
def ask_endpoint(req: AskRequest, request: Request, response: Response):
    """The body is exactly what it was in Week 4 (four keys). Week 11: the id of the request goes in the X-Request-ID header, so a
    support person can find the logged request from a complaint; an optional X-Caller-ID header says who sent it."""
    observability.forget_last_request()
    caller = (request.headers.get("x-caller-id") or "").strip()[:64] or None
    with observability.channel("api", caller=caller):
        result = _run(run_answer, req.question, req.mode)
    request_id = observability.last_request_id()
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return result


# --- Week 4: the inspection view ---

_INSPECT_STYLE = """
body { font: 14px/1.5 system-ui, sans-serif; margin: 24px; color: #222; }
h1 { font-size: 20px; margin-bottom: 4px; }
p.meta { color: #666; margin-top: 0; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #ddd; padding: 8px; vertical-align: top; text-align: left; }
th { background: #f4f4f4; position: sticky; top: 0; }
td.q { width: 22%; font-weight: 600; }
td.a { width: 30%; }
td.f { width: 48%; }
ol { margin: 0; padding-left: 18px; }
li { margin-bottom: 6px; }
.src { font-weight: 600; }
.via { color: #666; font-size: 12px; }
.snippet { color: #444; font-size: 12px; }
.refused { color: #b00; font-weight: 600; }
.empty { color: #666; }
"""


def _chunk_list_html(retrieved):
    """Render the fetched chunks as an ordered list showing WHY each was fetched."""
    if not retrieved:
        return '<span class="empty">nothing fetched</span>'
    items = []
    for chunk in retrieved:
        found_by = "+".join(chunk.get("retrievers") or []) or "?"
        score = chunk.get("score")
        score_text = f"{score:.4f}" if isinstance(score, (int, float)) else "n/a"
        ranks = []
        if chunk.get("dense_rank") is not None:
            ranks.append(f"dense#{chunk['dense_rank']}")
        if chunk.get("keyword_rank") is not None:
            ranks.append(f"keyword#{chunk['keyword_rank']}")
        detail = f" ({', '.join(ranks)})" if ranks else ""
        text = (chunk.get("text") or "").strip().replace("\n", " ")
        if len(text) > 240:
            text = text[:239] + "…"
        items.append(
            f'<li><span class="src">{escape(str(chunk.get("source", "unknown")))}</span> '
            f'<span class="via">score={score_text} via {escape(found_by + detail)}</span>'
            f'<br><span class="snippet">{escape(text)}</span></li>'
        )
    return "<ol>" + "".join(items) + "</ol>"


@app.get("/inspect", response_class=HTMLResponse)
def inspect_endpoint(limit: int = 20, ungrounded: bool = False):
    """Show recent requests as question / what was fetched / final answer.

    `limit` caps how many recent requests to show; `ungrounded=true` narrows it to the
    requests the app refused to answer, which is the fastest way to spot bad refusals.
    """
    traces = read_traces()
    if ungrounded:
        traces = [t for t in traces if t.get("grounded") is False]
    if limit and limit > 0:
        traces = traces[-limit:]

    if not traces:
        body = ('<p class="empty">No traces logged yet. Ask a question via '
                '<code>POST /ask</code> first.</p>')
        return HTMLResponse(f"<style>{_INSPECT_STYLE}</style>"
                            f"<h1>Inspection view</h1>{body}")

    rows = []
    for trace in reversed(traces):            # newest first, the useful order when debugging
        config = trace.get("config") or {}
        grounded = trace.get("grounded")
        answer_html = escape(str(trace.get("answer", "")))
        if grounded is False:
            answer_html += '<br><span class="refused">refused (said it does not know)</span>'
        rows.append(
            "<tr>"
            f'<td class="q">{escape(str(trace.get("question", "")))}'
            f'<br><span class="via">#{trace.get("line_no")} '
            f'{escape(str(trace.get("trace_id", "-")))} · '
            f'mode={escape(str(config.get("retrieval_mode", "?")))} · '
            f'top_k={escape(str(config.get("top_k", "?")))} · '
            f'chunks={escape(str(config.get("chunk_size", "?")))}</span></td>'
            f'<td class="f">{_chunk_list_html(trace.get("retrieved"))}</td>'
            f'<td class="a">{answer_html}</td>'
            "</tr>"
        )

    refused = sum(1 for t in traces if t.get("grounded") is False)
    return HTMLResponse(
        f"<style>{_INSPECT_STYLE}</style>"
        "<h1>Inspection view</h1>"
        f'<p class="meta">{len(traces)} request(s) · {refused} refused · '
        f"newest first · configured mode: {escape(settings.retrieval_mode)}</p>"
        "<table><thead><tr><th>Question</th><th>What was fetched (and why)</th>"
        "<th>Final answer</th></tr></thead><tbody>"
        + "".join(rows) +
        "</tbody></table>"
    )
