"""The MCP client side of the agent (Week 9): connect to MCP servers, discover their tools, hand them over.

MCP (the Model Context Protocol) is a standard "socket" between an AI app and tools. Three roles:

  HOST    the application that integrates a model and decides what to ask it and when to call a tool. Here that is
          our agent: the loop in app/agent/loop.py.
  CLIENT  a connector inside the host that speaks MCP to exactly ONE server. This file builds them.
  SERVER  a separate program that offers tools (app/mcp/servers/) and answers "list your tools" and "run this tool
          with these arguments".

Discovery is the point. The agent is never told which tools exist. At start-up this module connects to each
server listed in a config file, asks it "tools/list", vets every answer, and wraps what passes as an ordinary
`Tool` for the agent loop. Add a server to the config file and the agent has its tools, with no change to the
agent's code.

Transport is stdio: the host starts each server as a child process and they exchange JSON-RPC messages, one
per line, on its standard input and output (see scripts/mcp_raw_demo.py to watch them). A child process gets
only a small safe set of environment variables plus what the config gives it, so a server never inherits
your API key from the environment. It does run in the project folder, so it could still read a file there
such as .env: the guarantee is about inherited variables, not about files. A config entry runs a program on this
machine, so list only servers you trust. The MCP library is asynchronous and
the agent loop is not, so a background thread runs the event loop and this class offers plain blocking calls.
"""
import asyncio
import json
import sys
import threading
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from mcp import Client, StdioServerParameters

from app.agent.toolkit import Tool, ToolError
from app.config import BASE_DIR
from app.mcp.vetting import RESERVED_NAMES, is_plain_name, plain, vet_tool

GUARDED_NAMES = frozenset({"add_days", "calculate", "search_policies"})   # names the agent's prompt and the Week 8 guard key on
MAX_TOOLS_PER_SERVER = 40      # every accepted definition goes into every model request, so the number is capped
MAX_DEFINITION_CHARS = 60000   # ...and so is the total size of all the definitions together
MAX_SERVER_NAME = 32
MAX_PAGES = 20                 # tools/list is paged; a server that never stops paging is refused, not followed forever
MAX_RESULT_CHARS = 8000        # a longer tool result is cut, so one result cannot swamp the model's context
_WAIT_SLICE = 0.2              # seconds: waiting in short slices keeps Ctrl+C responsive on Windows


class MCPServerError(RuntimeError):
    """A server could not be started, did not answer in time, or misbehaved. The message names the server."""


@dataclass
class ServerSpec:
    name: str
    command: str
    args: list = field(default_factory=list)
    env: dict = field(default_factory=dict)
    cwd: str = None
    allow: list = None            # if set, only these tool names are accepted from this server (an empty list refuses all)


def load_specs(path):
    """Read a config file of the form {"servers": [{"name", "command", "args", "env", "cwd", "allow"}, ...]}."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    servers = data.get("servers") if isinstance(data, dict) else None
    if not isinstance(servers, list):
        found = f" (the top-level keys are {sorted(data)})" if isinstance(data, dict) else ""
        raise ValueError('the config must look like {"servers": [ ... ]}' + found)
    specs, seen = [], set()
    for entry in servers:
        if not isinstance(entry, dict):
            raise ValueError(f"every server entry must be an object, got {entry!r}")
        name = str(entry.get("name", "")).strip()
        command = entry.get("command")
        if not name or not isinstance(command, str) or not command.strip():
            raise ValueError(f"every server needs a name and a command, got {entry!r}")
        if not is_plain_name(name) or len(name) > MAX_SERVER_NAME:
            raise ValueError(f"server name {name!r} must be a plain identifier of at most {MAX_SERVER_NAME} characters "
                             "(letters, digits, underscore, hyphen; it can become part of a tool name)")
        if name in seen:
            raise ValueError(f"two servers are called {name!r}")
        seen.add(name)
        args, env, allow = entry.get("args", []), entry.get("env") or {}, entry.get("allow")
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise ValueError(f"server {name!r}: args must be a list of strings")
        if not isinstance(env, dict):
            raise ValueError(f"server {name!r}: env must be an object of names and values")
        if allow is not None and (not isinstance(allow, list) or not all(isinstance(item, str) for item in allow)):
            raise ValueError(f"server {name!r}: allow must be a list of tool names (an empty list refuses every tool)")
        specs.append(ServerSpec(name=name, command=command, args=list(args), env={str(k): str(v) for k, v in env.items()},
                                cwd=entry.get("cwd"), allow=allow))
    return specs


def _launch_parameters(spec):
    """How to start the server. 'python' means the interpreter running this host, so it works from any shell."""
    command = sys.executable if spec.command == "python" else spec.command
    return StdioServerParameters(command=command, args=spec.args, env=spec.env or None,
                                 cwd=spec.cwd or str(BASE_DIR))


def _definition_size(tool):
    """How many characters this tool's definition adds to every model request."""
    return len(json.dumps({"name": tool.name, "description": tool.description or "", "parameters": tool.input_schema or {}}, default=str))


def _seconds(count):
    return f"{count:.0f} second" + ("" if round(count) == 1 else "s")


# Characters that draw nothing and that Week 8's sanitizer strips before it matches (a zero-width space, a word joiner, the
# bidirectional embeddings, overrides and isolates). They are dropped from server text: written out as text they would hide a
# keyword split with one of them from that sanitizer.
_DROPPED = frozenset([0x200B, 0x2060] + list(range(0x202A, 0x202F)) + list(range(0x2066, 0x206A)))


def _hidden(char):
    """A character a server could use to act on the terminal or to smuggle text: a control other than a line break or tab,
    a tag character, or a lone surrogate (the request that carries one cannot be encoded). These are written out as text.
    Joiners, direction marks and the like that ordinary text needs (emoji, Arabic, Persian) are left alone."""
    return (unicodedata.category(char) in ("Cc", "Cs") and char not in chr(10) + chr(9)) or 0xE0000 <= ord(char) <= 0xE007F


def _printable(text):
    """Server text made safe to print and to send on: the hidden characters are written out as text, so a server cannot
    clear the screen or retitle the window through a result or an error message, and the characters in _DROPPED are
    dropped. A CR or CRLF line break becomes LF."""
    shown = []
    for char in text.replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10)):
        if ord(char) in _DROPPED:
            continue
        if not _hidden(char):
            shown.append(char)
        elif ord(char) < 256:
            shown.append(chr(92) + "x" + format(ord(char), "02x"))
        elif ord(char) <= 0xFFFF:
            shown.append(chr(92) + "u" + format(ord(char), "04x"))
        else:
            shown.append(chr(92) + "U" + format(ord(char), "08x"))
    return "".join(shown)


def _text_of(result):
    """The readable text of a tool result: its text blocks joined, or the structured content as JSON. Made safe to print
    (see _printable) and cut to MAX_RESULT_CHARS."""
    parts = [block.text for block in (result.content or []) if getattr(block, "type", "") == "text"]
    if parts:
        text = chr(10).join(parts)
    else:
        structured = getattr(result, "structured_content", None)
        text = json.dumps(structured, ensure_ascii=False) if structured is not None else ""
    shown = _printable(text[:2 * MAX_RESULT_CHARS])      # the work is bounded by the limit, not by the size of the reply
    if len(text) > 2 * MAX_RESULT_CHARS or len(shown) > MAX_RESULT_CHARS:
        shown = shown[:MAX_RESULT_CHARS] + f"... [cut: the result was {len(text)} characters long]"
    return shown


def _why(exc):
    """A short reason for a failure: the first real exception inside any exception group, with its type."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return _printable(f"{type(exc).__name__}: {str(exc).strip() or 'no message'}")[:200]


class MCPToolProvider:
    """Start the configured MCP servers, discover and vet their tools, and offer them as agent `Tool` objects.

    Use it as a context manager so the servers are always stopped:

        with MCPToolProvider(load_specs("mcp_servers.json")) as provider:
            run_agent(question, provider.tools)
    """

    def __init__(self, specs, call_timeout=30.0, connect_timeout=60.0, require_read_only=False):
        self.specs = list(specs)
        names = [spec.name for spec in self.specs]
        if len(set(names)) != len(names):
            raise ValueError(f"two servers are called {sorted(name for name in set(names) if names.count(name) > 1)[0]!r}")
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
        """Start every server at once, wait for each to list its tools, then vet them. Any failure stops them all."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="mcp-client", daemon=True)
        self._thread.start()
        try:
            starting = {spec.name: asyncio.run_coroutine_threadsafe(self._start_server(spec), self._loop) for spec in self.specs}
            discovered = {}
            for spec in self.specs:
                try:
                    discovered[spec.name] = self._wait(starting[spec.name], self.connect_timeout,
                                                       f"it did not finish starting within {_seconds(self.connect_timeout)}")
                except Exception as exc:        # Ctrl+C (BaseException) goes straight to the cleanup below
                    raise MCPServerError(f"the MCP server {spec.name!r} could not be started: {_why(exc)}") from exc
            self._build_tools(discovered)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self._loop is None:
            return
        try:
            self._wait(asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop), 25, "the shutdown took too long")
        except Exception:                      # shutting down must not hide the error that got us here
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(5)
        if not self._thread.is_alive():
            self._loop.close()
        self._loop = None

    @staticmethod
    def _wait(future, timeout, what):
        """Wait for a coroutine's result in short slices, so Ctrl+C is heard. TimeoutError(what) when it takes too long."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                return future.result(_WAIT_SLICE)
            except TimeoutError:
                if future.done():              # it finished while the slice ran out: its result, or the error it raised itself
                    return future.result()
                if time.monotonic() >= deadline:
                    future.cancel()
                    raise TimeoutError(what) from None

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
                tools, cursor, pages = [], None, 0
                while True:
                    page = await client.list_tools(cursor=cursor)
                    tools += list(page.tools)
                    cursor, pages = page.next_cursor, pages + 1
                    if not cursor:
                        break
                    if pages >= MAX_PAGES:
                        raise MCPServerError(f"it kept offering more tools after {MAX_PAGES} pages")
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
        for name, task in self._tasks.items():
            if name not in self._clients:      # never connected: there is nothing to close politely, so cancel it at once
                task.cancel()
        tasks = list(self._tasks.values())
        if tasks:
            _done, pending = await asyncio.wait(tasks, timeout=5)
            for task in pending:               # a server that never finished starting, or never lets go: cancel it
                task.cancel()
            if pending:
                await asyncio.wait(pending, timeout=5)

    # ------------------------------------------------------------------ discovery
    def _build_tools(self, discovered):
        """Vet every discovered tool first, then name the accepted ones.

        Names are made unique only among the tools that were ACCEPTED, so a refused tool cannot rename a good one.
        Two accepted tools that share a name get a server prefix, except for the names the agent's prompt and the
        Week 8 guard key on (GUARDED_NAMES): the first server that offers one keeps it and a later copy is refused,
        because a prefixed copy would escape the guard. A tool offered twice by one server, one whose name collides
        with the agent's own, and any tool past the per-server or the total size limit are refused.
        """
        accepted, total = [], 0
        for spec in self.specs:
            names_here, count_here = set(), 0
            for tool in discovered[spec.name]:
                ok, reason = vet_tool(spec.name, tool, allow=spec.allow, require_read_only=self.require_read_only)
                if ok and tool.name in names_here:
                    ok, reason = False, f"{spec.name}.{tool.name} is offered twice by this server"
                size = _definition_size(tool) if ok else 0
                if ok and count_here >= MAX_TOOLS_PER_SERVER:
                    ok, reason = False, f"{spec.name}.{tool.name} is past the limit of {MAX_TOOLS_PER_SERVER} tools from one server"
                elif ok and total + size > MAX_DEFINITION_CHARS:
                    ok, reason = False, f"{spec.name}.{tool.name} would take all the tool definitions past {MAX_DEFINITION_CHARS} characters"
                row = {"server": spec.name, "tool": tool.name, "accepted": ok, "reason": reason,
                       "description": (tool.description or "").strip()}
                self.rows.append(row)
                if not ok:
                    self.rejected.append(row)
                    continue
                names_here.add(tool.name)
                count_here, total = count_here + 1, total + size
                accepted.append((spec, tool, row))
        counts = Counter(tool.name for _spec, tool, _row in accepted)
        used = set(RESERVED_NAMES)
        for spec, tool, row in accepted:
            if tool.name in GUARDED_NAMES and counts[tool.name] > 1:
                if tool.name in used:
                    row["accepted"] = False
                    row["reason"] = (f"{spec.name}.{tool.name}: another server already provides {tool.name}, a name the agent's "
                                     "prompt and defences key on, so a second copy is refused and not renamed")
                    self.rejected.append(row)
                    continue
                public_name = tool.name
            else:
                public_name = tool.name if counts[tool.name] == 1 else f"{spec.name}__{tool.name}"
            if not is_plain_name(public_name) or public_name in used:
                row["accepted"] = False
                row["reason"] = (f"{spec.name}.{tool.name} would have to be called {plain(public_name)!r}, which is "
                                 "not a plain identifier of at most 64 characters that nothing else uses")
                self.rejected.append(row)
                continue
            used.add(public_name)
            row["public"] = public_name
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
            result = self._wait(asyncio.run_coroutine_threadsafe(client.call_tool(tool_name, arguments or {}), self._loop),
                                self.call_timeout, "no answer")
        except TimeoutError:
            raise ToolError(f"the MCP server {server!r} did not answer within {_seconds(self.call_timeout)}. Try something else.")
        except Exception as exc:
            raise ToolError(f"the MCP server {server!r} failed ({_why(exc)}). Try something else.")
        text = _text_of(result)
        if result.is_error:
            raise ToolError(text or f"{tool_name} reported an error without saying what.")
        return text

    def report(self):
        """What was discovered and what was refused, as printable lines (text from a server is shown escaped)."""
        accepted = [row for row in self.rows if row["accepted"]]
        lines = [f"discovered {len(self.rows)} tool(s) on {len(self.specs)} server(s); {len(accepted)} accepted, "
                 f"{len(self.rejected)} refused:"]
        for row in self.rows:
            mark = "  " if row["accepted"] else "X "
            summary = plain(" ".join(row["description"].split()), 70) if row["accepted"] else plain(row["reason"], 160)
            public = row.get("public")
            called = f"  [called {plain(public, 40)}]" if row["accepted"] and public and public != row["tool"] else ""
            lines.append(f"  {mark}{plain(row['server'], 30)}.{plain(row['tool'], 40):<22} {summary}{called}")
        return lines
