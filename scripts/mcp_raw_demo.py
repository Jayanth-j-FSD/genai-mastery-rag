"""Week 9: look at the raw MCP messages ONCE, so MCP stops being a mystery.

MCP is not magic. Over stdio it is plain JSON, one message per line, written to the server's
standard input and read from its standard output. This script starts the HRIS server and speaks to it with no
MCP library at all, only `subprocess` and `json`, printing every message in both directions. You will see:
the handshake (initialize, then a notification that the host is ready), the discovery request (tools/list),
a tool call (tools/call), and an error that comes back as data instead of a crash.

The AI model is not involved anywhere in this script. That is the point: the server only answers requests.

Run:
    python scripts/mcp_raw_demo.py
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.console import make_output_safe      # noqa: E402


def main():
    make_output_safe()
    server = subprocess.Popen([sys.executable, "-m", "app.mcp.servers.hris_server"], cwd=ROOT, text=True,
                              encoding="utf-8", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def send(message, note):
        print(f"\n--- {note}")
        text = json.dumps(message)
        print(f"HOST   -> SERVER  {text}")
        server.stdin.write(text + "\n")
        server.stdin.flush()

    def receive(wanted_id):
        """Read lines until the reply to request `wanted_id` arrives (servers may send other messages first)."""
        while True:
            line = server.stdout.readline()
            if not line:
                raise SystemExit("the server closed the connection")
            message = json.loads(line)
            shown = line.strip() if len(line) < 700 else line.strip()[:700] + " ..."
            print(f"SERVER -> HOST    {shown}")
            if message.get("id") == wanted_id:
                return message

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "raw-demo", "version": "0"}}},
             "1. HANDSHAKE: the host says hello, names the protocol version it speaks and what it can do")
        reply = receive(1)
        info = (reply.get("result") or {}).get("serverInfo", {})
        print(f"    -> the server replied with its own name {info.get('name')!r}, its version, and what it offers")
        send({"jsonrpc": "2.0", "method": "notifications/initialized"},
             "2. READY: a notification (it has no id, so no reply is expected) that the handshake is done")
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
             "3. DISCOVERY: the host asks what tools exist. Nobody wired these in by hand")
        listing = receive(2)
        names = [tool["name"] for tool in listing["result"]["tools"]]
        print(f"    -> {len(names)} tools discovered: {names}")
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "get_leave_balance", "arguments": {"employee_id": "E1001"}}},
             "4. A TOOL CALL: the host (not the server) decided to ask; the server only runs it and answers")
        receive(3)
        send({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
              "params": {"name": "get_leave_balance", "arguments": {"employee_id": "nobody"}}},
             "5. A RECOVERABLE ERROR: a bad argument comes back as a result flagged isError, with advice")
        receive(4)
    finally:
        server.stdin.close()
        server.wait(timeout=10)
    print("\nThe server never saw a question, a model or an agent: only these requests.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
