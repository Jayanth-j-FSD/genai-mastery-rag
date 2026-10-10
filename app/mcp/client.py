"""The MCP client side of the agent (Week 9): connect to MCP servers, discover their tools, hand them over.

MCP (the Model Context Protocol) is a standard "socket" between an AI app and tools. Three
roles, and the answer to "where does the AI run?" is in the first one:

  HOST    the program that contains the AI. Here that is our agent: the loop in app/agent/loop.py and the
          model it calls. THE AI RUNS HERE, ON YOUR SIDE, and nowhere else.
  CLIENT  a connector inside the host that speaks MCP to exactly ONE server. This file builds them.
  SERVER  a separate program that offers tools (app/mcp/servers/). It contains no AI and has no idea which
          AI, if any, is calling. It only answers "list your tools" and "run this tool with these arguments".

Discovery is the point. The agent is never told which tools exist. At start-up this module connects to each
server listed in a config file, asks it "tools/list", and wraps every answer as an ordinary `Tool` for the
agent loop. Add a server to the config file and the agent has its tools, with no change to the agent's code.

Transport is stdio: the host starts each server as a child process and they exchange JSON-RPC messages, one
per line, on its standard input and output (see scripts/mcp_raw_demo.py to watch them). A child process gets
only a small safe set of environment variables plus what the config gives it, so a server never inherits
your API key. The MCP library is asynchronous and the agent loop is not, so a background thread runs the
event loop and this class offers plain blocking calls.
"""
import asyncio
import json
import os
import sys
import threading
from dataclasses import dataclass, field

from mcp import Client, StdioServerParameters

from app.agent.toolkit import Tool, ToolError
from app.config import BASE_DIR
from app.mcp.vetting import vet_tool


@dataclass
class ServerSpec:
    name: str
    command: str
    args: list = field(default_factory=list)
    env: dict = field(default_factory=dict)
    cwd: str = None
    allow: list = None            # if set, only these tool names are accepted from this server


def load_specs(path):
    """Read a config file of the form {"servers": [{"name", "command", "args", "env", "cwd", "allow"}, ...]}."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    specs, seen = [], set()
    for entry in data.get("servers", []):
        name = str(entry.get("name", "")).strip()
        if not name or not entry.get("command"):
            raise ValueError(f"every server needs a name and a command, got {entry!r}")
        if name in seen:
            raise ValueError(f"two servers are called {name!r}")
        seen.add(name)
        specs.append(ServerSpec(name=name, command=entry["command"], args=list(entry.get("args", [])),
                                env={str(k): str(v) for k, v in (entry.get("env") or {}).items()},
                                cwd=entry.get("cwd"), allow=entry.get("allow")))
    return specs


def _launch_parameters(spec):
    """How to start the server. 'python' means the interpreter running this host, so it works from any shell."""
    command = sys.executable if spec.command == "python" else spec.command
    return StdioServerParameters(command=command, args=spec.args, env=spec.env or None,
                                 cwd=spec.cwd or str(BASE_DIR))


def _text_of(result):
    """The readable text of a tool result: its text blocks joined, or the structured content as JSON."""
    parts = [block.text for block in (result.content or []) if getattr(block, "type", "") == "text"]
    if parts:
        return "\n".join(parts)
    structured = getattr(result, "structured_content", None)
    return json.dumps(structured, ensure_ascii=False) if structured is not None else ""


class MCPToolProvider:
    """Start the configured MCP servers, discover and vet their tools, and offer them as agent `Tool` objects.

    Use it as a context manager so the servers are always stopped:

        with MCPToolProvider(load_specs("mcp_servers.json")) as provider:
            run_agent(question, provider.tools)
    """

    def __init__(self, specs, call_timeout=30.0, connect_timeout=60.0, require_read_only=False):
        self.specs = list(specs)
        self.call_timeout, self.connect_timeout, self.require_read_only = call_timeout, connect_timeout, require_read_only
        self.tools, self.rejected, self.rows = [], [], []
        self._loop = self._thread = None
        self._clients, self._stops, self._tasks = {}, {}, {}

    # ------------------------------------------------------------------ lifecycle
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_exc):
        self.close()
        return False

    def start(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="mcp-client", daemon=True)
        self._thread.start()
        try:
            discovered = {spec.name: self._submit(self._start_server(spec), self.connect_timeout) for spec in self.specs}
        except BaseException:
            self.close()
            raise
        self._build_tools(discovered)

    def close(self):
        if self._loop is None:
            return
        try:
            self._submit(self._shutdown(), 15)
        except Exception:                      # shutting down must not hide the error that got us here
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(5)
        if not self._thread.is_alive():
            self._loop.close()
        self._loop = None

    def _submit(self, coroutine, timeout):
        """Run a coroutine on the background loop and wait for it. Raises TimeoutError after `timeout` seconds."""
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout)
        except TimeoutError:
            future.cancel()
            raise

    # ------------------------------------------------------------------ one task per server
    async def _start_server(self, spec):
        loop = asyncio.get_running_loop()
        ready, stop = loop.create_future(), asyncio.Event()
        self._stops[spec.name] = stop
        self._tasks[spec.name] = loop.create_task(self._serve(spec, ready, stop))
        return await ready

    async def _serve(self, spec, ready, stop):
        """Keep one connection open from this task (the library needs to enter and leave it from the same task)."""
        try:
            async with Client(_launch_parameters(spec)) as client:
                tools, cursor = [], None
                while True:
                    page = await client.list_tools(cursor=cursor)
                    tools += list(page.tools)
                    cursor = page.next_cursor
                    if not cursor:
                        break
                self._clients[spec.name] = client
                ready.set_result(tools)
                await stop.wait()
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            if isinstance(exc, asyncio.CancelledError):
                raise
        finally:
            self._clients.pop(spec.name, None)

    async def _shutdown(self):
        for stop in self._stops.values():
            stop.set()
        if self._tasks:
            await asyncio.wait(list(self._tasks.values()), timeout=10)

    # ------------------------------------------------------------------ discovery
    def _build_tools(self, discovered):
        """Vet every discovered tool and wrap the accepted ones. Two servers offering one name get a server prefix."""
        counts = {}
        for tools in discovered.values():
            for tool in tools:
                counts[tool.name] = counts.get(tool.name, 0) + 1
        for spec in self.specs:
            for tool in discovered[spec.name]:
                ok, reason = vet_tool(spec.name, tool, allow=spec.allow, require_read_only=self.require_read_only)
                row = {"server": spec.name, "tool": tool.name, "accepted": ok, "reason": reason,
                       "description": (tool.description or "").strip()}
                self.rows.append(row)
                if not ok:
                    self.rejected.append(row)
                    continue
                public_name = tool.name if counts[tool.name] == 1 else f"{spec.name}__{tool.name}"
                self.tools.append(Tool(public_name, row["description"], dict(tool.input_schema or {"type": "object"}),
                                       self._caller(spec.name, tool.name)))

    def _caller(self, server, tool_name):
        def call(**arguments):
            return self._call(server, tool_name, arguments)
        return call

    def _call(self, server, tool_name, arguments):
        """Run one tool on its server. A failure comes back as a ToolError the model can read, never a crash."""
        client = self._clients.get(server)
        if client is None:
            raise ToolError(f"the MCP server {server!r} is not available. Try something else.")
        try:
            result = self._submit(client.call_tool(tool_name, arguments or {}), self.call_timeout)
        except TimeoutError:
            raise ToolError(f"the MCP server {server!r} did not answer within {self.call_timeout:.0f} seconds. Try something else.")
        except Exception as exc:
            raise ToolError(f"the MCP server {server!r} failed ({type(exc).__name__}). Try something else.")
        text = _text_of(result)
        if result.is_error:
            raise ToolError(text or f"{tool_name} reported an error without saying what.")
        return text

    def report(self):
        """What was discovered and what was refused, as printable lines."""
        accepted = [row for row in self.rows if row["accepted"]]
        lines = [f"discovered {len(self.rows)} tool(s) on {len(self.specs)} server(s); {len(accepted)} accepted, "
                 f"{len(self.rejected)} refused:"]
        for row in self.rows:
            mark = "  " if row["accepted"] else "X "
            summary = " ".join(row["description"].split())[:70] if row["accepted"] else row["reason"]
            lines.append(f"  {mark}{row['server']}.{row['tool']:<22} {summary}")
        return lines
