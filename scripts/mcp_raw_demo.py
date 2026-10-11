"""Week 9: look at the raw MCP messages ONCE, so MCP stops being a mystery.

MCP is not magic. Over stdio it is plain JSON, one message per line, written to the server's
standard input and read from its standard output. This script starts the HRIS server and speaks to it with no
MCP library at all, only `subprocess` and `json`, printing every message in both directions.

There are two ways to open a conversation, and the servers here answer both, so you see each in its own server
process:

  A. The newer way (protocol 2026-07-28), which the pinned `mcp` client tries first: there is no handshake.
     The host asks `server/discover`, then sends ordinary requests (`tools/list`, `tools/call`) that each say,
     in `_meta`, which protocol version they speak.
  B. The older way (protocol revisions 2024-11-05 to 2025-11-25), which a client falls back to for a server that
     does not know `server/discover`: an `initialize` request, a `notifications/initialized` message, then the same
     ordinary requests.

In both you will see discovery (`tools/list`), a tool call (`tools/call`) and an error that comes back as data
instead of a crash. This script calls no AI model: it only sends the requests printed below.

Run:
    python scripts/mcp_raw_demo.py
"""
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.console import make_output_safe      # noqa: E402

REPLY_TIMEOUT = 30                            # seconds to wait for any reply before giving up
CLIENT = {"name": "raw-demo", "version": "0"}
NEWER = "2026-07-28"
OLDER = "2025-06-18"


class Conversation:
    """One server process and the messages between it and us, printed in both directions."""

    def __init__(self, title):
        self.errors = tempfile.TemporaryFile()
        self.server = subprocess.Popen([sys.executable, "-m", "app.mcp.servers.hris_server"], cwd=ROOT, text=True,
                                       encoding="utf-8", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors)
        self.lines = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()       # a thread, so a silent server cannot hang us
        print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")

    def _read(self):
        for line in self.server.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _error_output(self):
        self.errors.seek(0)
        text = self.errors.read().decode("utf-8", "replace").strip()
        return f"\nWhat the server printed on its error output:\n{text[-800:]}" if text else ""

    def send(self, message, note):
        print(f"\n--- {note}")
        text = json.dumps(message)
        print(f"HOST   -> SERVER  {text}")
        self.server.stdin.write(text + "\n")
        self.server.stdin.flush()

    def receive(self, wanted_id):
        """Read lines until the reply to request `wanted_id` arrives (servers may send other messages first)."""
        while True:
            try:
                line = self.lines.get(timeout=REPLY_TIMEOUT)
            except queue.Empty:
                raise SystemExit(f"No reply from the server within {REPLY_TIMEOUT} seconds.{self._error_output()}")
            if line is None:
                raise SystemExit(f"The server closed the connection.{self._error_output()}")
            message = json.loads(line)
            shown = line.strip() if len(line) < 700 else line.strip()[:700] + " ..."
            print(f"SERVER -> HOST    {shown}")
            if message.get("id") == wanted_id:
                return message

    def close(self):
        try:
            self.server.stdin.close()
            self.server.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self.server.kill()
        self.errors.close()


def ordinary_requests(talk, meta=None, first_id=2):
    """discovery, a call, and a recoverable error: the same in both ways; only the newer way stamps `_meta`."""
    def params(body):
        return dict(body, _meta=meta) if meta else body

    talk.send({"jsonrpc": "2.0", "id": first_id, "method": "tools/list", "params": params({})},
              "DISCOVERY: the host asks what tools exist. Nobody wired these in by hand")
    names = [tool["name"] for tool in talk.receive(first_id)["result"]["tools"]]
    print(f"    -> {len(names)} tools discovered: {names}")
    talk.send({"jsonrpc": "2.0", "id": first_id + 1, "method": "tools/call",
               "params": params({"name": "get_leave_balance", "arguments": {"employee_id": "E1001"}})},
              "A TOOL CALL: the host asks the server to run one tool, and the server answers")
    talk.receive(first_id + 1)
    talk.send({"jsonrpc": "2.0", "id": first_id + 2, "method": "tools/call",
               "params": params({"name": "get_leave_balance", "arguments": {"employee_id": "nobody"}})},
              "A RECOVERABLE ERROR: a bad argument comes back as a result flagged isError, with advice")
    talk.receive(first_id + 2)


def newer_way():
    talk = Conversation(f"A. THE NEWER WAY (protocol {NEWER}): no handshake; every request says which version it speaks")
    meta = {"io.modelcontextprotocol/protocolVersion": NEWER, "io.modelcontextprotocol/clientInfo": CLIENT,
            "io.modelcontextprotocol/clientCapabilities": {}}
    try:
        talk.send({"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": meta}},
                  "DISCOVER THE SERVER: which protocol versions it speaks, what it offers, and its name")
        info = talk.receive(1)["result"]
        print(f"    -> supported versions {info.get('supportedVersions')}; the server calls itself "
              f"{info.get('_meta', {}).get('io.modelcontextprotocol/serverInfo', {}).get('name')!r}")
        ordinary_requests(talk, meta)
    finally:
        talk.close()


def older_way():
    talk = Conversation(f"B. THE OLDER WAY (protocol {OLDER}): a handshake first")
    try:
        talk.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": OLDER, "capabilities": {}, "clientInfo": CLIENT}},
                  "1. HANDSHAKE: the host says hello, names the protocol version it speaks and what it can do")
        info = (talk.receive(1).get("result") or {}).get("serverInfo", {})
        print(f"    -> the server replied with its own name {info.get('name')!r}, its version, and what it offers")
        talk.send({"jsonrpc": "2.0", "method": "notifications/initialized"},
                  "2. READY: a notification (it has no id, so no reply is expected) that the handshake is done")
        ordinary_requests(talk)
    finally:
        talk.close()


def main():
    make_output_safe()
    newer_way()
    older_way()
    print("\nThose were all the requests the server received.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
