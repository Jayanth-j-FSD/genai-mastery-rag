"""The agent's retriever-backed tool and the default toolbox.

The agent's tools are small functions plus a description the model reads (see
app/agent/toolkit.py for the wrapper, the error type and the two pure tools). This file adds the one tool
that needs the app's vector index, a search over the policy documents, and assembles the three tools of the
HR agent. `Tool`, `ToolError`, `calculate` and `add_days` are re-exported here so older imports keep working.
"""
from app.agent.toolkit import Tool, ToolError, add_days, calculate, calculator_tool, date_tool  # noqa: F401
from app.config import settings
from app.rag import retriever

# ---------------------------------------------------------------------------- search_policies

_MAX_PASSAGE_CHARS = 700          # keep each result short: long observations eat the token budget


def search_policies(query, top_k=3):
    """Search the policy documents. Returns numbered passages, each tagged with its source document."""
    if not isinstance(query, str) or not query.strip():
        raise ToolError("query must be a non-empty string describing what to look up.")
    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        raise ToolError("top_k must be a whole number between 1 and 6.")
    top_k = max(1, min(top_k, 6))
    chunks = retriever.retrieve_for_mode(query, top_k, settings.retrieval_mode)
    if not chunks:
        return "No passages found. Try different words."
    lines = []
    for number, chunk in enumerate(chunks, start=1):
        text = " ".join(chunk["text"].split())
        if len(text) > _MAX_PASSAGE_CHARS:
            text = text[:_MAX_PASSAGE_CHARS] + "..."
        lines.append(f"[{number}] [source: {chunk['source']}] {text}")
    return "\n".join(lines)


SEARCH_DESCRIPTION = (
    "Search the company policy documents (leave, notice periods, remote work, cloud access, expenses, "
    "security, the employee handbook) and get back numbered passages, each tagged with its source document. "
    "Use it for EVERY fact about a policy: never answer a policy question from memory. Search for one thing "
    "at a time with specific words, for example 'carry forward unused annual leave' or 'notice period "
    "permanent employee'. Do not use it for arithmetic or dates.")


def search_tool():
    return Tool("search_policies", SEARCH_DESCRIPTION,
                {"type": "object", "properties": {
                    "query": {"type": "string", "description": "what to look up, in a few specific words"},
                    "top_k": {"type": "integer", "description": "how many passages to return, 1 to 6 (default 3)"}},
                 "required": ["query"]},
                search_policies)


def default_tools():
    """The three tools of the HR agent. Descriptions say when to use each and when not to."""
    return [search_tool(), calculator_tool(), date_tool()]
