# Week 7: Agent loops, and when not to use them

## The task (from the brief)

*Build a small agent that completes a multi-step task using a couple of tools, with every step visible.
Then build the same thing as a plain fixed sequence and compare them on speed, cost, and reliability.*
The track line for HR policy: *race the HR agent against a fixed workflow.*

In plain words: an agent is a loop. The model looks at the question, either answers or asks for a tool,
the program runs the tool and shows the model the result, and this repeats until the model answers.
The point of the week is to build that loop by hand (one function of about a hundred lines), watch it work, make
sure it always stops, and then measure whether the loop was worth it against a fixed recipe that does
the same job in a set order.

## Definition of done: the mentor's four questions

1. Does the agent complete a genuinely multi-step task, with the steps visible?
2. Does it stop safely instead of looping forever?
3. Did you compare it against a plain fixed sequence with real numbers?
4. Can you say which one you would actually ship, and why?

## What was built, and which check it serves

| Piece | File | Serves |
|---|---|---|
| The loop: think, call a tool, read the result, repeat. Every step is recorded (what the model asked, what the tool returned, tokens, seconds) | `app/agent/loop.py` | 1 |
| Three tools with descriptions that say when to use them: `search_policies` (the app's own retriever), `calculate` (exact arithmetic, parsed with `ast`, never `eval`), `add_days` (exact calendar dates) | `app/agent/tools.py` | 1 |
| Four stop conditions, each ending the run with a named reason: a step limit, a total-token budget, a wall-clock timeout, and a repeated-call guard. The token budget and the timeout are checked between model calls, so they are soft: the call that crosses one still completes and is counted. A provider error and an empty reply also end the run with their own reasons (`error`, `empty_reply`) and never become an answer | `app/agent/loop.py`, `app/config.py` | 2 |
| Tool failures are conversation, not crashes: a bad argument comes back to the model as advice it can act on | `app/agent/loop.py`, `app/agent/tools.py` | 2 |
| Memory: old tool results are shortened, and a `remember` tool keeps a few facts in view on every step | `app/agent/memory.py` | 1 |
| The fixed workflow: retrieve once, one model call | `app/agent/workflow.py` | 3 |
| The race: nine tasks, several runs each, both approaches, scored by the same rule checks as Week 6, with calls, tokens and seconds | `evals/race.py`, `evals/agent_tasks.py`, `scripts/race_agent.py` | 3 |
| Watch one run live, step by step, or turn the limits down and watch it stop | `scripts/run_agent.py`, `app/agent/display.py` | 1, 2 |
| Real recorded runs: a multi-step run with six tool calls, and a run stopped by the step limit | `docs/week7/example-run.md`, `docs/week7/example-stop.md` | 1, 2 |

The nine tasks (`evals/agent_tasks.py`) are mixed on purpose: one plain lookup (the fixed workflow should
win), arithmetic, date arithmetic, a question that needs two documents, a conflict between documents, and
one question the documents cannot answer (the agent must stop and say so). The sentences each answer is built
from (`source_facts`) are checked against the real documents by a unit test, and the figures worked out from
them are checked against the two tools, so a task cannot go stale silently. The phrases the rule checks look for
in an answer are the task author's expectations and are not tested against the documents.

## Run it

```powershell
.\.venv\Scripts\python.exe scripts\run_agent.py "I will have 25 unused leave days at year end. How many can I carry forward?"
.\.venv\Scripts\python.exe scripts\run_agent.py --workflow "How many weeks of paid parental leave are there?"
.\.venv\Scripts\python.exe scripts\run_agent.py --max-steps 2 "..."     # watch it stop on the step limit
.\.venv\Scripts\python.exe scripts\race_agent.py --label rerun --repeats 3   # a new race: about 120 model calls
.\.venv\Scripts\python.exe scripts\race_agent.py --show race --rescore         # re-read the saved race, no model calls
```

The race throttles to `LLM_RPM` and stops cleanly, keeping what finished, if a daily quota runs out, if the
provider fails three runs in a row, or if a run crashes. The committed race is saved as `race`; a new race needs
its own `--label` (as above), because a complete saved race is not replaced unless you pass `--force`. In the committed race an agent run took 3.5 model calls on average and a workflow run exactly 1.

The saved race has two scores. The rule checks were tightened after it ran (the two tasks that need two
documents now require both to be cited), and `--rescore` recomputes every stored run under the current checks
without calling the model. `findings.md` section 2 explains the difference.

## The part that is yours

Check 4 asks which one you would ship, and why. `findings.md` has the generated numbers (reliability,
cost, speed, per task); the decision and the reasons are blank on purpose, because the brief asks for your
judgement and an agent cannot honestly make it for you.

## Design choices worth knowing

- **Native tool calling instead of parsing "Thought/Action" text.** The original ReAct paper has the model
  write its reasoning and tool request as text that the program parses. Today's APIs return the tool
  request as structured data, which is more reliable. The loop is the same shape: reason, act, observe.
- **No framework.** The brief asks for the loop by hand so it is never magic. A LangGraph version is a
  fair later comparison and is listed as deferred in `CHANGES.md`.
- **Seconds are counted inside model calls only.** Waiting for the free tier's rate limit is excluded,
  because it depends on the quota and would be charged to whichever approach makes more calls. Wall-clock
  time is recorded too.
