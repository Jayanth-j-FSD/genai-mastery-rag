# Week 9: MCP, the standard way agents reach tools and data

## The task (from the brief)

*Connect your agent to a tool over MCP so it discovers the tool instead of you wiring it in. Then build a small
MCP server that exposes one real capability of your app, and have someone else's agent call it.* The track
line for HR policy: *bolt on the HRIS server without touching the agent.*

In plain words: until now every tool was written into the agent by hand, and no other team could reuse it.
MCP (the Model Context Protocol) is a standard socket between an AI app and tools. This week the agent
learns its tools by asking servers "what can you do?", and the policy search becomes a server that any
other MCP host can use. MCP is plumbing: it makes tools reusable and swappable. It does not make the AI
smarter, and that is the honest way to describe it to a client.

## Definition of done: the mentor's four questions

1. Does the agent use a tool through MCP, discovered rather than hard-coded?
2. Can you add a second tool without changing the agent's code?
3. Did you build your own server that another person's agent could call?
4. Can you explain, in plain words, where the AI runs and where it does not?

## What was built, and which check it serves

| Piece | File | Serves |
|---|---|---|
| The client side: starts the servers listed in a config file, asks each "tools/list", vets the answers, and hands them to the unchanged agent loop as ordinary tools | `app/mcp/client.py`, `mcp_servers.json` | 1, 2 |
| `scripts/run_agent_mcp.py`: the agent run with discovered tools, plus `--list` to see only the discovery | `scripts/run_agent_mcp.py` | 1, 2 |
| The HRIS server (synthetic data, read-only, access scoped): leave balance, employee summary, direct reports | `app/mcp/servers/hris_server.py`, `app/mcp/data/hris_employees.json` | 2 |
| The policy-search server: our app's own capability, published for any host (one tool, one resource, one prompt) | `app/mcp/servers/policy_server.py` | 3 |
| The utils server: the Week 7 calculator and date tools, now discoverable instead of wired in | `app/mcp/servers/utils_server.py` | 1 |
| Another person's agent: a separate script that imports nothing from this project and calls our server with a different client library | `scripts/other_agent_demo.py` | 3 |
| The raw messages, once: the JSON-RPC handshake, discovery, a call and an error, with no MCP library | `scripts/mcp_raw_demo.py` | 4 |
| Checking a tool before trusting it: name, description (tool poisoning), schema, allowlist, read-only | `app/mcp/vetting.py` | safety |

`app/agent/loop.py` is not changed this week. A unit test fails if the loop, the tools or the client ever
mention a particular server or import `app.mcp`.

## Run it

```powershell
.\.venv\Scripts\python.exe scripts\mcp_raw_demo.py                      # the raw messages (no model, no key)
.\.venv\Scripts\python.exe scripts\run_agent_mcp.py --list              # what the agent discovers
.\.venv\Scripts\python.exe scripts\run_agent_mcp.py "Employee E1001 asks how many annual leave days they have left, and how many of those they could carry forward at year end"
.\.venv\Scripts\python.exe scripts\other_agent_demo.py                  # someone else's client calling our policy server
```

To add a capability, add a server entry to `mcp_servers.json`. To take one away, delete the entry. The agent
code does not change either way.

## Where the AI runs (the plain-words version)

```
   YOUR SIDE (the host)                                   A SEPARATE PROGRAM (the server)
  +--------------------------------------+               +------------------------------+
  |  the agent loop  <---->  the model   |               |  offers tools:               |
  |   (app/agent/loop.py)    (Gemini API)|               |   get_leave_balance, ...     |
  |        |                             |               |  contains NO AI              |
  |   MCP client  ---- JSON-RPC over --------stdio------> |  does not know who is calling|
  +--------------------------------------+               +------------------------------+
```

- **Host**: the program that contains the AI. Here it is the agent plus the model calls it makes. The AI
  runs here, on your side, and decides when to call a tool.
- **Client**: a connector inside the host that talks MCP to exactly one server.
- **Server**: a separate program that offers tools. It has no AI in it and does not know which AI, if any,
  is calling. It answers "list your tools" and "run this tool" and nothing else.

That is why a server you build can be used by any host, and why connecting to somebody else's server means
trusting their tool descriptions and their results, not their intelligence.

## What an MCP server can offer, and how the messages travel

- **Tools**: functions the model may ask the host to call (this week's focus).
- **Resources**: data a host can read, such as the policy server's list of documents (`policy://documents`).
- **Prompts**: ready-made prompt templates, such as the policy server's `answer_from_policies`.
- **Transport**: how the messages travel. Here it is **stdio**: the host starts the server as a child process
  and they exchange one JSON message per line on its standard input and output. The other standard transport
  is HTTP, used when the server runs somewhere else.
- **The handshake**: `initialize` (the host names the protocol version it speaks, the server answers with its
  own), a `notifications/initialized` message, then `tools/list` and `tools/call`. `scripts/mcp_raw_demo.py`
  prints every one of them.

## Keeping it safe

Everything below is built and tested except remote MCP, which is described but not built.

- **Access control, at the server.** `HRIS_SCOPE=basic` (the default) does not offer the payroll tool at all,
  so an agent connected to it cannot discover it, let alone call it. All tools are read-only and say so
  (`readOnlyHint`). Least privilege means not offering what is not needed.
- **Checking a tool before trusting it** (`app/mcp/vetting.py`). A tool description is text the model reads
  and believes, so it is an input an attacker can write ("tool poisoning"). Each discovered tool is refused
  if its name is not a plain identifier, its description is missing, enormous or contains instruction-like
  text, its schema is odd, or it is not on the operator's allowlist; optionally, if it is not declared
  read-only (`--require-read-only`). This is a gate, not a guarantee.
- **Screening results.** A tool that passes can still return poisoned text. Run the agent with `--defense`
  and the Week 8 layers screen every result and validate the final answer.
- **A child server gets no secrets.** The client passes a server only a small safe set of environment
  variables plus what the config file names, so a server never inherits the API key.
- **Remote MCP and auth (not built).** Over HTTP a server needs authentication (OAuth is the standard
  route) and the host must not send it more than it needs. A stdio server on your own machine inherits your
  machine's trust boundary; a remote one does not.

## Connecting someone else's host to our server

Any MCP host takes the same two facts: a command and a folder. For a host that reads an `mcpServers`
settings file the entry looks like this (replace the path with where this project is checked out):

```json
{"mcpServers": {"hr-policy": {"command": "<path to AI-Task>/.venv/Scripts/python.exe",
                              "args": ["-m", "app.mcp.servers.policy_server"],
                              "cwd": "<path to AI-Task>"}}}
```

The index must exist first (`python scripts/ingest.py`).

## The part that is yours

Check 4 asks you to explain, in plain words, where the AI runs and where it does not. The diagram above is a
reference, not your answer. `findings.md` has a blank for it, and the other numbers there are generated.
