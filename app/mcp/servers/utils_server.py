"""Exact arithmetic and date arithmetic as an MCP server (Week 9).

In Week 7 these two tools were wired into the agent by hand. Here the same functions are
published through MCP instead, so an agent can DISCOVER them like any other tools. It imports only
`app/agent/toolkit.py`, which has no heavy dependencies, so it starts in a fraction of a second.

Run by hand (it waits silently for a client):
    python -m app.mcp.servers.utils_server
"""
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError as MCPToolError

from app.agent import toolkit

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
mcp = FastMCP("utils", instructions="Exact arithmetic and calendar-date tools. Read-only.")


@mcp.tool(name="calculate", description=toolkit.CALCULATE_DESCRIPTION, annotations=READ_ONLY)
def calculate(expression: str) -> str:
    try:
        return toolkit.calculate(expression)
    except toolkit.ToolError as exc:
        raise MCPToolError(str(exc))


@mcp.tool(name="add_days", description=toolkit.ADD_DAYS_DESCRIPTION, annotations=READ_ONLY)
def add_days(date: str, days: int) -> str:
    try:
        return toolkit.add_days(date, days)
    except toolkit.ToolError as exc:
        raise MCPToolError(str(exc))


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False, log_level="WARNING")
