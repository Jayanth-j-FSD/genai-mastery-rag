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
- **Two different client libraries on purpose.** Our agent uses the official `mcp` client. The "another
  person's agent" demo uses `fastmcp`'s client. A server that works with both is evidence that it follows the
  standard and not one library's habits.
- **One long-lived task per server.** The MCP library enters and leaves a connection from the same asyncio task,
  and our agent loop is synchronous, so a background thread runs the event loop with one task per server and
  the provider offers plain blocking calls with a timeout.
- **A child server gets no secrets.** Only the library's small safe set of environment variables plus what the
  config names. A test proves a variable set in the host is not visible to the server.
- **Access control at the server, by not offering.** The HRIS payroll tool exists only when the server is
  started with `HRIS_SCOPE=payroll`; under the default scope an agent cannot discover it.
- **Vetting is a gate, not a guarantee.** It refuses odd names, missing or enormous descriptions, descriptions
  that contain instruction-like text (tool poisoning), odd schemas and anything off an operator's allowlist, and
  optionally anything not declared read-only. A tool that passes can still return poisoned results, which is
  what Week 8's screening of results is for (`--defense`).
- **A server error is a recoverable observation.** A tool that reports an error, times out or whose server
  dies comes back to the model as an `ERROR:` text it can act on, not as a crash.
- **Tool names get a server prefix only on a collision**, so the common case stays readable.

## Considered and deferred

| Technique | Why not this week |
|---|---|
| Remote MCP over HTTP with OAuth | Needs a hosted server and an identity provider. Documented in the README, not built. |
| Pinning a tool's definition after it is vetted (so a later change is refused, the "rug pull") | A good next defence; this week vets at discovery only. |
| The agent using MCP resources and prompts | The agent uses tools. Resources and prompts are shown on the policy server and in the other-agent demo. |
| Server-initiated requests (sampling, elicitation, roots) | The host has no use for a server asking its model to think. |
| Multi-agent systems and agent-to-agent protocols | The next topics of the module, not this week's. |
