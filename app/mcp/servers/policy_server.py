"""The app's own policy search, offered to any MCP host (Week 9: build a server another agent can call).

Searching the HR policy documents is the one real capability of this app. Published through
MCP, any other team's agent can discover `search_policies` and call it without knowing anything about our
code. It also shows the other two things a server can offer besides tools: a RESOURCE (data a host can read,
here the list of documents) and a PROMPT (a ready-made prompt template).

It needs the index, so run `python scripts/ingest.py` first. Run by hand (it waits silently for a client):
    python -m app.mcp.servers.policy_server
"""
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError as MCPToolError

from app.agent import tools
from app.config import settings
from app.rag import loader

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
mcp = FastMCP("hr-policy", instructions="Search the company HR policy documents. Read-only.")


@mcp.tool(name="search_policies", description=tools.SEARCH_DESCRIPTION, annotations=READ_ONLY)
def search_policies(query: str, top_k: int = 3) -> str:
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
