# Week 9: findings

This is the file the mentor reads. Every output below was printed by the command shown above it, so it can be run
again. Section 7, where the AI runs and where it does not, is blank on purpose: the brief asks for your own
explanation, and nothing else in this folder answers it.

## 1. Discovery: the agent's tools come from the servers (check 1)

`python scripts/run_agent_mcp.py --list`

```
discovered 6 tool(s) on 3 server(s); 6 accepted, 0 refused:
    policy.search_policies        Search the company policy documents (leave, notice periods, remote ...
    utils.calculate              Do exact arithmetic. Use it whenever the answer needs a sum, differ...
    utils.add_days               Add calendar days to a date (negative days go backwards) and get th...
    hris.get_leave_balance      Annual leave entitlement, days taken and days remaining, and sick d...
    hris.get_employee_summary   Name, department, manager, start date and employment status (probat...
    hris.list_direct_reports    The employee ids and names of the people who report directly to one...
```

The three tools wired into the agent in Week 7 (`search_policies`, `calculate`, `add_days`) keep the names the Week 7
prompt and the Week 8 guard already use, so the policy and utils servers publish them under those names. The three HRIS
tools are named nowhere in the agent. Week 9 changed no file of the agent, the retriever, the settings or the evals:
`git diff --stat week-8-agent-failure-modes week-9-mcp -- app/agent app/rag app/config.py app/llm.py evals` prints nothing.
A test, `test_the_agent_machinery_never_names_a_particular_server`, fails if any file of the agent, the client or the
vetting gate mentions the demo HRIS server by name, or if the loop imports `app.mcp`.

A live run with these tools, on `gemini-3-flash-preview`, 2026-10-11, recorded before the review fixes to the client (the agent, the tools and the model are as now):

`python scripts/run_agent_mcp.py --model gemini-3-flash-preview "Employee E1001 asks how many annual leave days they have left, and how many of those they could carry forward at year end"`

```
discovered 6 tool(s) on 3 server(s); 6 accepted, 0 refused:
    policy.search_policies        Search the company policy documents (leave, notice periods, remote wor
    utils.calculate              Do exact arithmetic. Use it whenever the answer needs a sum, differenc
    utils.add_days               Add calendar days to a date (negative days go backwards) and get the r
    hris.get_leave_balance      Annual leave entitlement, days taken and days remaining, and sick days
    hris.get_employee_summary   Name, department, manager, start date and employment status (probation
    hris.list_direct_reports    The employee ids and names of the people who report directly to one ma

Question: Employee E1001 asks how many annual leave days they have left, and how many of those they could carry forward at year end

[step 1] CALL   get_leave_balance({"employee_id": "E1001"})
          RESULT {"employee_id":"E1001","as_of":"2026-10-01","annual_entitlement_days":18,"annual_taken_days":4,"annual_remaining_days":14,"sick_taken_days":2}
          (909 tokens, 2.0s)
[step 2] CALL   search_policies({"query": "carry forward annual leave"})
          RESULT [1] [source: Acme-Leave-Policy-2026.md] # ACME LEAVE POLICY 2026 Effective date: 2026-01-01 ## 1. Eligibility All regular full-time employees become eligible for the annual leave allowance after completing 30 calendar d...
          (1131 tokens, 1.4s)
[step 3] CALL   search_policies({"query": "carry forward unused leave Synthetic_HR_Policy_RAG_Test_Dataset.md"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] # Northstar Digital Solutions Pvt. Ltd. � Synthetic HR Policy Handbook **Document purpose:** Synthetic test data for RAG applications. **Version:** 2026.1 **Effectiv...
          (1707 tokens, 2.3s)
[step 4] CALL   search_policies({"query": "carry forward limit"})
          RESULT [1] [source: Acme-Leave-Policy-2026.md] # ACME LEAVE POLICY 2026 Effective date: 2026-01-01 ## 1. Eligibility All regular full-time employees become eligible for the annual leave allowance after completing 30 calendar d...
          (2427 tokens, 2.5s)
[step 5] CALL   search_policies({"query": "Northstar Digital Solutions carry forward days"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] ### Effective Dates Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to ...
          (2676 tokens, 1.9s)
[step 6] CALL   search_policies({"query": "annual leave allowance days"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company may pe...
          (2666 tokens, 2.5s)
[step 7] CALL   search_policies({"query": "carry forward Synthetic_HR_Policy_RAG_Test_Dataset.md"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] # Northstar Digital Solutions Pvt. Ltd. � Synthetic HR Policy Handbook **Document purpose:** Synthetic test data for RAG applications. **Version:** 2026.1 **Effectiv...
          (3106 tokens, 94.5s)
[step 8] CALL   search_policies({"query": "carry forward limit Synthetic_HR_Policy_RAG_Test_Dataset.md"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] # Northstar Digital Solutions Pvt. Ltd. � Synthetic HR Policy Handbook **Document purpose:** Synthetic test data for RAG applications. **Version:** 2026.1 **Effectiv...
          (3455 tokens, 1.7s)

NO ANSWER: the run was stopped before a final answer.

stopped because: max_steps | 8 step(s) | 8 model call(s), 18077 tokens
```

Read straight off that output: the agent called `get_leave_balance` x 1, `search_policies` x 7. The run ended without an answer (stopped because `max_steps`, 8 steps, 18077 tokens). Four or more calls to one tool is what Week 8 calls `over-calling`; it is a property of the agent loop and the model, not of MCP.

A second run with the Week 8 call budget could not be made: the model's free daily quota was used up. Its command and result are left open:

`AGENT_MAX_CALLS_PER_TOOL=3 python scripts/run_agent_mcp.py --model <a model with quota left> "Employee E1001 asks how many annual leave days they have left, and how many of those they could carry forward at year end"`

Result: not run yet.

## 2. Adding a capability without changing the agent (check 2)

`python scripts/run_agent_mcp.py --config mcp_servers.no-hris.json --list`

```
discovered 3 tool(s) on 2 server(s); 3 accepted, 0 refused:
    policy.search_policies        Search the company policy documents (leave, notice periods, remote ...
    utils.calculate              Do exact arithmetic. Use it whenever the answer needs a sum, differ...
    utils.add_days               Add calendar days to a date (negative days go backwards) and get th...
```

The only difference between that run and the one in section 1 is the config file: `diff mcp_servers.json mcp_servers.no-hris.json`
shows the HRIS entry, and nothing else, being the line that is missing.

```
4,6c4
<     {"name": "utils", "command": "python", "args": ["-m", "app.mcp.servers.utils_server"]},
<     {"name": "hris", "command": "python", "args": ["-m", "app.mcp.servers.hris_server"],
<      "allow": ["get_leave_balance", "get_employee_summary", "list_direct_reports"]}
---
>     {"name": "utils", "command": "python", "args": ["-m", "app.mcp.servers.utils_server"]}
```

Tests that pin it: `test_adding_a_server_adds_its_tools_and_needs_no_change_to_the_agent` and
`test_adding_a_server_to_the_config_adds_its_tools_with_no_code_change`.

## 3. Our server, someone else's agent (check 3)

`python scripts/other_agent_demo.py`

```
Discovered tools:
  search_policies: Search the company policy documents (leave, notice periods, remote work, cloud access, exp...

Calling search_policies('notice period for a permanent employee'):

[1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company may periodically review this rule and communicate changes through official internal channels. - Standard notice period is **60 calendar days** for confirmed employees and **30 calendar days** during probation, unless the employment agreement specifies otherwise.
[2] [source: Acme-Employment-Terms-2026.md] # ACME EMPLOYMENT TERMS POLICY 2026 Effective date: 2026-03-01 ## 1. Scope This policy applies to regular full-time Acme employees. A separate written agreement may provide a longer notice period, in which case the written agreement controls. ## 2. Probationary employees An employee who is still within the probationary period must provide 7 calendar days of written notice before resigning. Acme may waive some or all of this notice at its discretion. ## 3. Permanent employees After successful completion of probation, a permanent employee must provide 30 calendar days of written notice before resigning. The notice period begins on the date People Operations receives the written resignation. ##...

Reading the resource policy://documents:
  Acme-Employment-Terms-2026.md
  Acme-Leave-Policy-2026.md
  Nexora_Tech_Azure_Cloud_Data_Access_Policy.md
  Northstar-Remote-Work-Policy-2026.md
  Synthetic_HR_Policy_RAG_Test_Dataset.md
  benefits.md
  expenses.md
  security-policy.md
  support-faq.md

Prompts the server offers: ['answer_from_policies']
```

`scripts/other_agent_demo.py` is written as if by someone else: a test, `test_the_other_agent_imports_nothing_from_this_project`,
checks that it imports nothing from this project. It uses `fastmcp`'s client, a different library from the official
`mcp` client our own agent uses, and is told only a command and a folder. It discovered the policy server's one tool,
called it, read the `policy://documents` resource and listed the server's one prompt.

## 4. The raw messages, once

`python scripts/mcp_raw_demo.py` (no MCP library and no model: a bare subprocess and `json`)

```

==============================================================================
A. THE NEWER WAY (protocol 2026-07-28): no handshake; every request says which version it speaks
==============================================================================

--- DISCOVER THE SERVER: which protocol versions it speaks, what it offers, and its name
HOST   -> SERVER  {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientInfo": {"name": "raw-demo", "version": "0"}, "io.modelcontextprotocol/clientCapabilities": {}}}}
SERVER -> HOST    {"jsonrpc":"2.0","id":1,"result":{"_meta":{"io.modelcontextprotocol/serverInfo":{"name":"hris","version":"4.1.0"}},"ttlMs":0,"cacheScope":"private","supportedVersions":["2026-07-28"],"capabilities":{"logging":{},"prompts":{"listChanged":false},"resources":{"subscribe":false,"listChanged":false},"tools":{"listChanged":false},"extensions":{"io.modelcontextprotocol/ui":{}}},"instructions":"Read-only access to a SYNTHETIC HR information system: leave balances, an employee summary and direct reports. Employee ids look like E1001.","resultType":"complete"}}
    -> supported versions ['2026-07-28']; the server calls itself 'hris'

--- DISCOVERY: the host asks what tools exist. Nobody wired these in by hand
HOST   -> SERVER  {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientInfo": {"name": "raw-demo", "version": "0"}, "io.modelcontextprotocol/clientCapabilities": {}}}}
SERVER -> HOST    {"jsonrpc":"2.0","id":2,"result":{"cacheScope":"private","resultType":"complete","tools":[{"_meta":{"fastmcp":{"tags":[]}},"annotations":{"destructiveHint":false,"openWorldHint":false,"readOnlyHint":true},"description":"Annual leave entitlement, days taken and days remaining, and sick days taken, for one employee.\n\nUse it when a question is about THIS employee's own leave (how many days they have left). For what the\ncompany policy allows, search the policy documents instead. Employee ids look like E1001.","inputSchema":{"type":"object","additionalProperties":false,"properties":{"employee_id":{"type":"string"}},"required":["employee_id"]},"name":"get_leave_balance","outputSchema":{"additio ...
    -> 3 tools discovered: ['get_leave_balance', 'get_employee_summary', 'list_direct_reports']

--- A TOOL CALL: the host asks the server to run one tool, and the server answers
HOST   -> SERVER  {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_leave_balance", "arguments": {"employee_id": "E1001"}, "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientInfo": {"name": "raw-demo", "version": "0"}, "io.modelcontextprotocol/clientCapabilities": {}}}}
SERVER -> HOST    {"jsonrpc":"2.0","id":3,"result":{"content":[{"text":"{\"employee_id\":\"E1001\",\"as_of\":\"2026-10-01\",\"annual_entitlement_days\":18,\"annual_taken_days\":4,\"annual_remaining_days\":14,\"sick_taken_days\":2}","type":"text"}],"isError":false,"resultType":"complete","structuredContent":{"employee_id":"E1001","as_of":"2026-10-01","annual_entitlement_days":18,"annual_taken_days":4,"annual_remaining_days":14,"sick_taken_days":2},"_meta":{"io.modelcontextprotocol/serverInfo":{"name":"hris","version":"4.1.0"}}}}

--- A RECOVERABLE ERROR: a bad argument comes back as a result flagged isError, with advice
HOST   -> SERVER  {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_leave_balance", "arguments": {"employee_id": "nobody"}, "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientInfo": {"name": "raw-demo", "version": "0"}, "io.modelcontextprotocol/clientCapabilities": {}}}}
SERVER -> HOST    {"jsonrpc":"2.0","id":4,"result":{"content":[{"text":"employee_id must look like E1001 (the letter E and four digits).","type":"text"}],"isError":true,"resultType":"complete","_meta":{"io.modelcontextprotocol/serverInfo":{"name":"hris","version":"4.1.0"}}}}

==============================================================================
B. THE OLDER WAY (protocol 2025-06-18): a handshake first
==============================================================================

--- 1. HANDSHAKE: the host says hello, names the protocol version it speaks and what it can do
HOST   -> SERVER  {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "raw-demo", "version": "0"}}}
SERVER -> HOST    {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","capabilities":{"logging":{},"prompts":{"listChanged":true},"resources":{"subscribe":false,"listChanged":true},"tools":{"listChanged":true}},"serverInfo":{"name":"hris","version":"4.1.0"},"instructions":"Read-only access to a SYNTHETIC HR information system: leave balances, an employee summary and direct reports. Employee ids look like E1001."}}
    -> the server replied with its own name 'hris', its version, and what it offers

--- 2. READY: a notification (it has no id, so no reply is expected) that the handshake is done
HOST   -> SERVER  {"jsonrpc": "2.0", "method": "notifications/initialized"}

--- DISCOVERY: the host asks what tools exist. Nobody wired these in by hand
HOST   -> SERVER  {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
SERVER -> HOST    {"jsonrpc":"2.0","id":2,"result":{"tools":[{"_meta":{"fastmcp":{"tags":[]}},"annotations":{"destructiveHint":false,"openWorldHint":false,"readOnlyHint":true},"description":"Annual leave entitlement, days taken and days remaining, and sick days taken, for one employee.\n\nUse it when a question is about THIS employee's own leave (how many days they have left). For what the\ncompany policy allows, search the policy documents instead. Employee ids look like E1001.","inputSchema":{"properties":{"employee_id":{"type":"string"}},"required":["employee_id"],"type":"object","additionalProperties":false},"name":"get_leave_balance","outputSchema":{"type":"object","additionalProperties":true},"title":"G ...
    -> 3 tools discovered: ['get_leave_balance', 'get_employee_summary', 'list_direct_reports']

--- A TOOL CALL: the host asks the server to run one tool, and the server answers
HOST   -> SERVER  {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_leave_balance", "arguments": {"employee_id": "E1001"}}}
SERVER -> HOST    {"jsonrpc":"2.0","id":3,"result":{"content":[{"text":"{\"employee_id\":\"E1001\",\"as_of\":\"2026-10-01\",\"annual_entitlement_days\":18,\"annual_taken_days\":4,\"annual_remaining_days\":14,\"sick_taken_days\":2}","type":"text"}],"isError":false,"structuredContent":{"employee_id":"E1001","as_of":"2026-10-01","annual_entitlement_days":18,"annual_taken_days":4,"annual_remaining_days":14,"sick_taken_days":2}}}

--- A RECOVERABLE ERROR: a bad argument comes back as a result flagged isError, with advice
HOST   -> SERVER  {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_leave_balance", "arguments": {"employee_id": "nobody"}}}
SERVER -> HOST    {"jsonrpc":"2.0","id":4,"result":{"content":[{"text":"employee_id must look like E1001 (the letter E and four digits).","type":"text"}],"isError":true}}

Those were all the requests the server received.
```

## 5. Keeping it safe: what is built, and the test that shows it

| Control | Where | Test |
|---|---|---|
| The default scope cannot even discover the payroll tool | `app/mcp/servers/hris_server.py` | `test_the_default_scope_cannot_even_discover_the_payroll_tool` |
| A poisoned tool description is refused, a clean one kept | `app/mcp/vetting.py` | `test_a_server_whose_tool_description_is_poisoned_is_refused_and_a_clean_one_is_kept`, `test_instructions_hidden_in_a_description_are_refused_as_tool_poisoning` |
| An allowlist keeps only the named tools and says why for the rest | `app/mcp/client.py` | `test_an_allowlist_keeps_only_the_named_tools_and_says_why_for_the_rest` |
| Optionally refuse tools not declared read-only | `app/mcp/vetting.py` | `test_require_read_only_refuses_tools_that_do_not_declare_it` |
| A child server does not inherit the host's secrets | `app/mcp/client.py` | `test_a_server_does_not_inherit_the_hosts_secrets_but_does_get_what_the_config_names` |
| A slow tool is a tool error, not a hang | `app/mcp/client.py` | `test_a_tool_that_takes_too_long_is_a_tool_error_not_a_hang` |
| A server-side error reaches the model as advice it can act on | `app/mcp/client.py` | `test_a_server_side_error_becomes_a_tool_error_with_the_servers_advice`, `test_the_agent_loop_shows_that_error_to_the_model_as_an_observation` |

Not built, only described in `README.md`: remote MCP over HTTP with authentication, and pinning a tool's definition
after it has been vetted so that a later change is refused.

## 6. The gate

`python scripts/check_all.py --strict`

```
== check_all ==
[ok] compile     122 files
[ok] imports     48 modules, 30 scripts
[ok] --help      26 scripts
[ok] unit tests  777 tests in 74.661s

All checks passed.
```

## 7. Yours to write

Where does the AI run, and where does it not? Say it in your own words, as you would to a client who asks
whether adding MCP makes the assistant smarter:

>
