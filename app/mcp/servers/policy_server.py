"""The app's own policy search, offered to any MCP host (Week 9: build a server another agent can call).

Searching the HR policy documents is the one real capability of this app. Published through
MCP, any other team's agent can discover `search_policies` and call it without knowing anything about our
code. It also shows the other two things a server can offer besides tools: a RESOURCE (data a host can read,
here the list of documents) and a PROMPT (a ready-made prompt template).

It needs the index, so run `python scripts/ingest.py` first. Run by hand (it waits silently for a client):
    python -m app.mcp.servers.policy_server
"""
import os

os.environ.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")    # no update check: it would write a cache file outside this project
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")       # chroma's usage statistics stay off

from typing import Annotated                                  # noqa: E402

from fastmcp import FastMCP                                   # noqa: E402
from fastmcp.exceptions import ToolError as MCPToolError      # noqa: E402
from pydantic import Field                                    # noqa: E402

from app.agent import tools                                   # noqa: E402
from app.config import settings                               # noqa: E402
from app.rag import loader, store                             # noqa: E402

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
mcp = FastMCP("hr-policy", instructions="Search the company HR policy documents. Read-only.")


@mcp.tool(name="search_policies", description=tools.SEARCH_DESCRIPTION, annotations=READ_ONLY)
def search_policies(query: Annotated[str, Field(description="what to look up, in a few specific words")],
                    top_k: Annotated[int, Field(description="how many passages to return, 1 to 6 (default 3)")] = 3) -> str:
    if store.count_chunks() == 0:                            # a missing index must not look like "no passages matched"
        raise MCPToolError("the policy index is empty or missing. Run `python scripts/ingest.py` first, then ask again.")
    try:
        return tools.search_policies(query, top_k)
    except tools.ToolError as exc:
        raise MCPToolError(str(exc))


@mcp.resource("policy://documents")
def list_documents() -> str:
    """The names of the policy documents this server can search, one per line."""
    return "\n".join(sorted(doc["source"] for doc in loader.load_documents(settings.corpus_dir)))


@mcp.prompt()
def answer_from_policies(question: str) -> str:
    """A prompt that asks for a policy answer that is grounded in the documents and cites them."""
    return (f"Answer this HR policy question using only the policy documents, searching with search_policies, "
            f"and cite each document as [source: <name>]. If they do not say, reply that you do not know.\n\n{question}")


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False, log_level="WARNING")
