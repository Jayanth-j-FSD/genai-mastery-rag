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
| Another person's agent: a separate script that imports nothing from this project and calls our server with the other well-known client, `fastmcp`'s | `scripts/other_agent_demo.py` | 3 |
| The raw messages, once: both ways of opening a conversation (the newer `server/discover` and the older `initialize` handshake), discovery, a call and an error, with no MCP library | `scripts/mcp_raw_demo.py` | 4 |
| Checking a tool before trusting it: its name, every piece of text the model reads (description, title, every string in the schema), schema size, allowlist, read-only | `app/mcp/vetting.py` | safety |

No file of the agent, the retriever, the settings or the evals is changed this week. The three tools that were
wired into the agent in Week 7 keep the names the agent's prompt and the Week 8 guard already use; the three HRIS
tools are named nowhere in the agent. A unit test fails if any file of the agent, the client or the vetting gate
mentions the demo HRIS server by name, or if the loop imports `app.mcp`.

## Run it

```powershell
.\.venv\Scripts\python.exe scripts\mcp_raw_demo.py                      # the raw messages (no model, no key)
.\.venv\Scripts\python.exe scripts\run_agent_mcp.py --list              # what the agent discovers
.\.venv\Scripts\python.exe scripts\run_agent_mcp.py "Employee E1001 asks how many annual leave days they have left, and how many of those they could carry forward at year end"
.\.venv\Scripts\python.exe scripts\other_agent_demo.py                  # someone else's client calling our policy server
```

The policy search needs the index, so run `scripts\ingest.py` first: without it the policy server answers with a
plain "the policy index is empty or missing" error, and `run_agent_mcp.py` says so before it starts anything.

To add a capability, add a server entry to `mcp_servers.json`. To take one away, delete the entry. The agent
code does not change either way.

## Where the AI runs (the plain-words version)

```
   YOUR SIDE (the host)                                   A SEPARATE PROGRAM (the server)
  +--------------------------------------+               +------------------------------+
  |  the agent loop  ---->  a hosted     |               |  offers tools:               |
  |   (app/agent/loop.py)   model (Gemini|               |   get_leave_balance, ...     |
  |        |                API, at Google)|             |  contains NO AI, calls none  |
  |   MCP client  ---- JSON-RPC over --------stdio------> |  sees the client's name and  |
  +--------------------------------------+               |  version, not any model      |
                                                         +------------------------------+
```

- **Host**: the program that contains the AI integration. Here it is the agent plus the model calls it makes. The
  host decides what to ask the model and when to call a tool. In this project the model is a hosted API
  (Gemini), so its computation happens at the provider, and every tool result the agent receives is sent there as
  part of the next request. What the brief means by "the AI runs on your side" is that the host drives it: no
  model runs in, or is called by, a server.
- **Client**: a connector inside the host that talks MCP to exactly one server.
- **Server**: a separate program that offers tools. It has no AI in it and does not call one. It answers
  "list your tools" and "run this tool", and it sees the client's name and version (`clientInfo`) and the
  requests, nothing about which model, if any, is behind the client.

That is why a server you build can be used by any host, and why connecting to somebody else's server means
trusting their tool descriptions and their results, not their intelligence.

## What an MCP server can offer, and how the messages travel

- **Tools**: functions the model may ask the host to call (this week's focus).
- **Resources**: data a host can read, such as the policy server's list of documents (`policy://documents`).
- **Prompts**: ready-made prompt templates, such as the policy server's `answer_from_policies`.
- **Transport**: how the messages travel. Here it is **stdio**: the host starts the server as a child process
  and they exchange one JSON message per line on its standard input and output. The other standard transport
  is HTTP, used when the server runs somewhere else.
- **Opening a conversation**, in two ways, and the servers here answer both. The newer way (protocol
  2026-07-28, which the pinned `mcp` client tries first) has no handshake: the host asks `server/discover`, then
  sends ordinary requests (`tools/list`, `tools/call`) that each say in `_meta` which protocol version they speak.
  The older way (2025-06-18 and before, which a client falls back to for a server that does not know
  `server/discover`) is an `initialize` request, a `notifications/initialized` message, then the same requests.
  `scripts/mcp_raw_demo.py` prints every message of both.

## Keeping it safe

Everything below is built and tested except remote MCP, which is described but not built.

- **Access control, at the server, by what it offers.** `HRIS_SCOPE=basic` (the default) does not offer the
  payroll tool at all, so an agent connected to it cannot discover it, let alone call it. All tools are read-only
  and say so (`readOnlyHint`). Least privilege means not offering what is not needed. This is a choice made when
  the server starts, not a decision about who is asking: any employee id can be read by any agent connected to the
  server. Deciding per caller needs the server to know the caller, which is what authentication (OAuth, below) is for.
- **Checking a tool before trusting it** (`app/mcp/vetting.py`). A tool definition is text the model reads
  and believes, so it is an input an attacker can write ("tool poisoning"). Every piece of it is checked, not only
  the description: the title and every string in the input schema too. A tool is refused if its name is not a
  plain identifier or is one the agent reserves (`remember`); if any of that text is missing, enormous, contains
  control, zero-width, private-use or unassigned characters, mixes alphabets inside a word, or contains
  instruction-like text (read across line breaks); if its schema is odd or over 8,000 characters; or if it is not on
  the operator's allowlist; optionally, if it is not declared read-only (`--require-read-only`). Two tools that
  share a name get a server prefix only when both were accepted, so a refused tool cannot rename a good one. This is
  a gate, not a guarantee: a plain instruction that uses none of the sanitizer's trigger words passes, and a harmless
  description that happens to use one is refused (`test_what_the_gate_cannot_do_is_written_down_as_facts`).
- **Screening results.** A tool that passes can still return poisoned text. Run the agent with `--defense`
  and the Week 8 layers screen every result and validate the final answer. One limit, shown by a test: the
  validator wants a retrieved policy document to be cited (or the plain refusal), so with `--defense` an answer
  that comes only from another tool, such as the HRIS, is withheld. The script says so before it runs. Also, the
  Week 8 argument guard keys on the tool names `add_days` and `calculate`; keep those names unprefixed.
- **A child server inherits no environment variables of yours.** The client passes a server only the
  library's small safe set of variables plus what the config file names, so a server never inherits the API key
  from the environment. It does run in the project folder, so it could read a file there such as `.env`: the
  guarantee is about inherited variables, not files. A secret a server needs would have to be written in
  `mcp_servers.json`, which is committed; expanding `${NAME}` from the environment is not built.
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

The index must exist first (`python scripts/ingest.py`). A host that ignores `cwd` needs the absolute path to the
project on `PYTHONPATH` instead, or a launcher that changes directory first, because the server is started with
`-m app.mcp.servers.policy_server`.

## The part that is yours

Check 4 asks you to explain, in plain words, where the AI runs and where it does not. The diagram above is a
reference, not your answer. `findings.md` has a blank for it, and the other numbers there are generated.
