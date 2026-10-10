# Week 9: what changed, and why

Everything here is a new file or an additive change. `app/agent/loop.py`, the tools and the defences are not
touched: a unit test fails if the loop, the tools or the client ever mention a particular server, or if the
loop imports `app.mcp`. That is the point of the week: the agent gets new capabilities without changing.

**Left for you.** Explaining in your own words where the AI runs and where it does not is blank in `findings.md`.

## What was added

- `app/mcp/client.py` and `app/mcp/vetting.py`: the client side. It starts the servers named in
  `mcp_servers.json`, discovers their tools, vets each one, and hands the survivors to the unchanged agent
  loop as ordinary tools.
- `app/mcp/servers/`: three small MCP servers built with `fastmcp`: HRIS (synthetic employee data, read-only,
  access scoped), policy search (the app's own capability, plus a resource and a prompt) and utils (the
  Week 7 calculator and date tools, now discoverable). `app/mcp/data/hris_employees.json` is the synthetic data.
- `scripts/run_agent_mcp.py` (the agent with discovered tools), `scripts/mcp_raw_demo.py` (the raw JSON-RPC
  messages, no MCP library) and `scripts/other_agent_demo.py` (a script that imports nothing from this project
  and calls our policy server with a different client library).
- `fastmcp==4.1.0` and `mcp==2.3.0` pinned in `requirements.txt`.

## Decisions

- **stdio transport.** The host starts each server as a child process and they trade one JSON message per line.
  It needs no network, no ports and no authentication, and it is what local MCP hosts use. HTTP is the other
  standard transport and is described, not built (see below).
- **Two client libraries on purpose.** Our agent uses the official `mcp` client. The "another person's agent"
  demo uses `fastmcp`'s client. They are two front-ends over the same SDK, and `fastmcp`'s server is built on it
  too, so this shows the servers do not depend on one client's calling style. It is not independent evidence that
  the protocol was implemented twice.
- **One long-lived task per server.** The MCP library enters and leaves a connection from the same asyncio task,
  and our agent loop is synchronous, so a background thread runs the event loop with one task per server and
  the provider offers plain blocking calls with a timeout.
- **A child server inherits none of the host's environment variables.** Only the library's small safe set plus
  what the config names. A test proves a variable set in the host is not visible to the server. It is not a
  boundary around files: the server runs in the project folder and could read `.env`. A secret a server needs would
  have to be written in the committed `mcp_servers.json`; expanding `${NAME}` from the environment is deferred.
- **Access control at the server, by not offering.** The HRIS payroll tool exists only when the server is
  started with `HRIS_SCOPE=payroll`; under the default scope an agent cannot discover it.
- **Vetting is a gate, not a guarantee.** It checks every piece of text the model reads (description, title and
  every string in the input schema), not only the description, and refuses odd or reserved names, control,
  zero-width, private-use and unassigned characters, words that mix alphabets, instruction-like text read across
  line breaks, odd or oversized schemas and anything off an operator's allowlist, and optionally anything not
  declared read-only. A plain instruction with no trigger words passes, and a harmless description that uses a
  trigger word is refused (both are tests). A tool that passes can still return poisoned results, which is what
  Week 8's screening of results is for (`--defense`).
- **A server error is a recoverable observation.** A tool that reports an error, times out or whose server
  dies comes back to the model as an `ERROR:` text it can act on, not as a crash.
- **Tool names are decided after vetting.** A server prefix is added only when two ACCEPTED tools share a name, so
  a refused tool cannot rename a good one (the Week 8 guard keys on the name `add_days`). A tool offered twice by
  one server, one named `remember` (the loop's own), or one whose prefixed name would not be a plain identifier of
  at most 64 characters is refused.
- **Startup is concurrent and every failure names the server.** All servers are started at once, each wait has its
  own timeout, a server that never answers is cancelled so its process stops, and the error says which server and why
  (`MCPServerError`). Waiting is done in short slices so Ctrl+C is heard. A server that offers more than 20 pages of
  tools is refused, and a tool result over 8,000 characters is cut.

## Considered and deferred

| Technique | Why not this week |
|---|---|
| Remote MCP over HTTP with OAuth | Needs a hosted server and an identity provider. Documented in the README, not built. |
| Pinning a tool's definition after it is vetted (so a later change is refused, the "rug pull") | A good next defence; this week vets at discovery only. |
| The agent using MCP resources and prompts | The agent uses tools. Resources and prompts are shown on the policy server and in the other-agent demo. |
| Expanding `${NAME}` from the environment in the config, so a secret need not be written in it | The only secret-free servers are used this week; the hole is documented. |
| Per-caller authorization at the HRIS server | It needs the server to know who is asking, which is authentication (OAuth over HTTP), the remote-MCP topic that is described and not built. |
| A Week 9 validator that counts discovered tools as sources under `--defense` | It would loosen the Week 8 check that an answer cites a retrieved document; the limit is documented and tested instead. |
| Server-initiated requests (sampling, elicitation, roots) | The host has no use for a server asking its model to think. |
| Multi-agent systems and agent-to-agent protocols | The next topics of the module, not this week's. |
