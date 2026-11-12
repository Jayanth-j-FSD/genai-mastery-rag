# Week 7: what changed, and why

Everything here is a new file or an additive, default-valued setting. Nothing from Weeks 3 to 6 was
rewritten: the app's `/ask` path, the retriever, the generator and the eval harness behave exactly as before.

## What was added

- `app/agent/` (the loop, the tools, the memory, the fixed workflow) and `evals/race.py`,
  `evals/agent_tasks.py`, with `scripts/run_agent.py` and `scripts/race_agent.py`.
- Three settings in `app/config.py`: `AGENT_MAX_STEPS` (8), `AGENT_MAX_TOTAL_TOKENS` (40000) and
  `AGENT_TIMEOUT_SECONDS` (120). They are the stop conditions; a caller can override each per run.
- Unit tests for the loop, the tools, the memory, the workflow, the race arithmetic and the tasks.

## Decisions

- **The loop reuses `app/llm.py`.** One place already throttles to the free tier's per-minute limit,
  retries, times out and counts tokens, so the agent inherits all of that, and a used-up daily quota
  propagates instead of being swallowed.
- **The stop conditions are checked between model calls.** The token budget and the timeout stop the run
  before the next call is spent. They are soft: the call that crosses one still completes and is counted (a test
  pins a 1,100-token run against a 1,000-token budget), and one slow call can run past the timeout. The step
  limit is the loop bound itself.
- **An empty reply is a failure, never a refusal.** A model reply with no text and no tool request ends the run
  as `empty_reply` with no answer, in the agent and in the workflow. Counting it as "I don't know" would have let
  an unanswerable task pass for free.
- **A repeated call is warned once and ends the run on the third time.** The model is told it already
  made that exact call and was shown the result; a second identical repeat in a row ends the run with
  `repeated_call`. A repeat followed by a new request is forgiven. "Exact" means the same tool and the same
  arguments as JSON, so a different key order or spacing is still the same call.
- **Tool failures become observations.** An unknown tool, bad JSON, a wrong argument name, a tool
  exception: all come back as `ERROR: ...` text the model can react to, so one bad call does not end a run. A
  wrong argument name is detected before the call, by binding the arguments to the tool's signature, so a
  `TypeError` raised inside a tool is reported as a tool failure and not as the model's mistake.
- **`calculate` never uses `eval`.** The expression is parsed with `ast` and only numbers and `+ - * / // % **`
  are walked; the exponent and the size of integer results are capped so a hostile expression cannot burn CPU.
- **The race scores both approaches with the Week 6 rule checks**, rebuilding the passages the agent saw from
  its own search results, so the same definition of "right" applies to both.

## Found by running it

The first live run of the agent, on Gemini's OpenAI-compatible endpoint, failed on its second model call with
HTTP 400: "Function call is missing a thought_signature". Gemini's thinking models attach a `thought_signature`
to every tool call (in `extra_content`) and refuse the next request unless it is sent back unchanged, and the
loop was dropping it. It now echoes any extra data on a tool call back exactly as it came (`_echo_call` in
`app/agent/loop.py`, two tests). Mocked tests could not have found this; it is how that provider behaves.

The first race scored the agent 26 of 27 and the workflow 27 of 27. A closer look then showed that two
tasks passed on weak checks, and re-scoring the same stored answers under the corrected checks gives 25 and 24
(`findings.md`, section 2). Both numbers are reported.

Smaller changes that came from running it:

- `search_policies` and the two pure tools were split: `app/agent/toolkit.py` (the `Tool` wrapper, the error
  type, `calculate`, `add_days`; no heavy imports) and `app/agent/tools.py` (the retriever-backed search and
  the default toolbox). Week 9 offers the pure tools from a tiny server without loading the vector store.
- `app/agent/display.py` holds the step printer, so every script that runs an agent shows steps the same way.
- The race summary has a per-task cost table, and `scripts/race_agent.py --show LABEL` re-prints a saved
  race with no model calls.

## Considered and deferred

| Technique | Why not this week |
|---|---|
| LangChain / LangGraph | The brief asks for the loop by hand so it is not magic. Re-implementing the same agent in LangGraph and comparing is a good later exercise. |
| Long-term memory (a vector store of past conversations, mem0) | These tasks are single conversations. Short-term memory (shortened old results, a notes tool) is built; cross-session memory has nothing to remember yet. |
| Parsing "Thought / Action" text (the original ReAct format) | Structured tool calls are more reliable than parsing text, and the loop is the same shape. |
| Planner-executor and self-reflection loops | They add model calls per task, and the first question is whether the plain loop is worth its calls at all. |
| A smarter fixed workflow (one search per sub-question, then a calculator step) | It is the fairer competitor and is worth building next. The workflow here is the simplest honest recipe (retrieve once, answer once), so a result in the workflow's favour on the simple tasks is not a surprise and a result in the agent's favour on the hard ones is a real finding. |
