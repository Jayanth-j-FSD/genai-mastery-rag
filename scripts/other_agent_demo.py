"""Week 9, mentor check #3: another person's agent calls OUR server.

This script is written as if by someone else. It imports NOTHING from this project, only the
public `fastmcp` client library, which is a different MCP client from the one our own agent uses. It is told a
single thing, how to start our policy server (a command and a folder), and from there it discovers what the
server offers, searches the HR policies, and reads the list of documents. A real outside agent would hand the
discovered tools to its own model; the model is left out here so the server's side is easy to see.

If this works, any MCP host can use our policy search: a desktop AI app, an IDE assistant, a colleague's agent.
In those hosts you would paste the same command and folder into their MCP settings (see docs/week9/README.md).

Run (after `python scripts/ingest.py`):
    python scripts/other_agent_demo.py
    python scripts/other_agent_demo.py "how long is the notice period for a permanent employee"
"""
import asyncio
import os
import sys

os.environ.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")      # an update check would write a cache file outside the project

from fastmcp import Client      # noqa: E402
from fastmcp.exceptions import ToolError      # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def main(query):
    # The whole "integration": a command to launch the server, and the folder to launch it in.
    config = {"mcpServers": {"hr-policy": {"command": sys.executable, "args": ["-m", "app.mcp.servers.policy_server"],
                                           "cwd": PROJECT}}}
    async with Client(config) as client:
        tools = await client.list_tools()
        print("Discovered tools:")
        for tool in tools:
            print(f"  {tool.name}: {' '.join((tool.description or '').split())[:90]}...")
        print(f"\nCalling search_policies({query!r}):\n")
        result = await client.call_tool("search_policies", {"query": query, "top_k": 2})
        for block in result.content:
            print(block.text)
        print("\nReading the resource policy://documents:")
        for item in await client.read_resource("policy://documents"):
            print("  " + item.text.replace("\n", "\n  "))
        prompts = await client.list_prompts()
        print(f"\nPrompts the server offers: {[prompt.name for prompt in prompts]}")


if __name__ == "__main__":
    try:
        asyncio.run(main(" ".join(sys.argv[1:]) or "notice period for a permanent employee"))
    except ToolError as exc:                  # the server refused the call and said why (for example: no index yet)
        print(f"\nThe server answered with an error: {exc}")
        sys.exit(1)
