# Week 10: a team of agents, raced against the single agent

## The task (from the brief)

*Build a small team, a manager plus two specialists, and race it against your single agent on the same test set.
Report quality, speed, tokens, and cost for both, and give an honest verdict on which to keep.* The track line for HR
policy: *race the policy squad against your single agent.*

In plain words: until now one agent did everything (Weeks 7 to 9). This week the same job is split between a manager
and two specialists, and both designs answer the same nine questions with the same model. The numbers say what the
split cost and what it bought. The honest verdict, which design to keep and why, is written by you, even if the
team lost.

## Definition of done: the mentor's four questions

1. Did they race the team against the single agent on the SAME tests?
2. Did they report all four numbers: quality, speed, tokens, cost?
3. Is the verdict backed by the numbers, even if the team lost?
4. Can they say when multi-agent would be worth it, and when it wouldn't?

Copied from the brief (title: "Multi-Agent & A2A: With Evidence, Not Fashion"). The only changes are an em dash written as a
colon and a curly apostrophe written as a plain one, and, in the task sentence above, two em dashes written as commas, to
keep this repository's plain-ASCII style.

## What was built, and which check it serves

| Piece | File | Serves |
|---|---|---|
| The team: a manager that hands one question at a time to a researcher (search only) or a calculator (arithmetic and dates only), each an ordinary agent loop; the agents' steps merged in time order and every agent's calls, tokens and seconds counted apart | `app/agent/team.py` | 1, 2 |
| A record of every model call, kept per piece of work, so each arm is measured by the same instrument and the team's cost can be split by agent | `app/llm.py` (`call_scope`) | 2 |
| Tokens to money with a price YOU state; no price table; a missing price is "not stated", never zero | `app/pricing.py`, `PRICE_*` settings | 2 |
| The team as a third runner in the Week 7 race harness (the Week 7 race itself is unchanged) | `evals/race.py` | 1 |
| The race: the same nine tasks, interleaved, saved after every run, resumable, frozen to a commit | `scripts/race_team.py` | 1 |
| The report: quality, speed, tokens and cost per arm and per agent, with the numbers a reader needs to judge them | `evals/team_report.py` | 2, 3 |
| A pilot on questions that are not race tasks, to shake the team down without tuning on the test set | `scripts/pilot_team.py` | 1 |
| The prediction, written before the race and checked as arithmetic afterwards | `evals/team_prediction.py`, `scripts/check_team_prediction.py` | 3 |
| Watching the team work, one question at a time | `scripts/run_agent.py --team`, `app/agent/display.py` | 1 to 4 |

No file of the single agent's loop, its tools, its prompt or the evals' rule checks is changed: the team is built from
the same loop (`run_agent`) with its own prompts and tool lists. A unit test fails if any sentence the team borrows from
the single agent's prompt stops being word for word in it.

## Run it

```powershell
.\.venv\Scripts\python.exe scripts\run_agent.py --team --model gemini-3.1-flash-lite-preview "How long is a password reset link valid?"   # watch one team run
.\.venv\Scripts\python.exe scripts\race_team.py --plan                               # what a race would take: no model calls
.\.venv\Scripts\python.exe scripts\pilot_team.py --label pilot-1 --model gemini-3.1-flash-lite-preview   # shake-down on non-race questions
.\.venv\Scripts\python.exe scripts\race_team.py --label wk10 --model gemini-3.5-flash-lite              # the race: agent against team
.\.venv\Scripts\python.exe scripts\race_team.py --label wk10 --model gemini-3.5-flash-lite --resume     # carry on after a quota stop
.\.venv\Scripts\python.exe scripts\race_team.py --show wk10                          # the report: free
.\.venv\Scripts\python.exe scripts\check_team_prediction.py wk10                     # the prediction against the numbers: free
```

A race needs the index (`scripts\ingest.py`) and names its model: an alias such as `gemini-flash-lite-latest` can move
under you, so it is refused. A race on code that is not committed is refused too; only a pilot, whose label starts
with `pilot-`, may run on an uncommitted tree. Dollars appear only when you pass `--price-in`, `--price-out` and
`--price-source`; see "Cost" below.

## How the team is built

```
question --> manager --ask_policy_researcher(question)--> researcher --search_policies--> the policy index
                |  \--ask_calculator(question)---------> calculator --calculate, add_days
                v
            final answer
```

- The **manager** has no tool except the two hand-offs. It reads the question, asks a specialist one thing at a time, and
  writes the final answer, citing what the researcher named.
- A **specialist** is an ordinary agent loop with its own prompt and a short tool list. It sees ONLY the question the
  manager sent, never the manager's conversation, so that question is the whole hand-off.
- Every agent runs the loop with the same defaults as the single agent, scratchpad memory included. The defences of
  Week 8 are off for both designs.
- The team shares ONE token budget and ONE time limit (the same defaults as the single agent, widened to 300 seconds for
  both designs in the race because the free tier's rate-limit pauses count). Each specialist is handed what is left. The
  step limits are per agent (manager 8, researcher 8, calculator 4), so the team's total number of model calls is not
  capped the way a single agent's is: the report prints this under CAPS.
- A specialist that cannot finish comes back to the manager as an error it can react to (ask again, or say it could not
  find the answer). A daily-quota stop inside a specialist is raised, never swallowed.
- The registry of the two specialists (`SPECIALISTS`: name, description, tools, step limit) is plain Python data. The
  manager's hand-off tools are worded from it.

## The race

The same nine tasks (`evals/agent_tasks.py`), the same rule checks, the same model and the same limits on tokens and
time, run as the single agent and as the team, three times each. The runs are interleaved: repeat by repeat, task by task,
every arm once before the next task, with the order rotating, so a quota that ends the race part-way leaves every arm with
almost the same runs and the provider's mood at any hour is shared. `--noise` adds a second identical single-agent arm
(`agent-2`), and `--workflow` adds the fixed workflow of Week 7 as a reference.

What a result records, so a reader can check that the arms differ only where they are meant to: the requested model and the
model the provider says answered, the limits and call budget in force, what each arm was run with (prompts hashed, tool
descriptions hashed, memory), a table of what each agent may use, the search settings, the corpus (every document with a
hash), the git commit, whether the code was committed, and a hash of the files that decide the result. `--resume` refuses to
carry a race on after any of them changed; the race must then be run again under a new label and the old file stays.

## The four numbers, and how each is measured

- **Quality.** A run succeeds when it finished AND passed the rule checks (the same checks, from `evals/checks.py`). The
  report gives the rate with a 95% interval, and, for the same task and repeat under two arms, the discordant pairs with the
  exact McNemar p. It also lists every run that did not succeed, with the checks it failed and the start of its answer, so
  each can be read and judged as a failure of substance or of form. The rule checks match words, so a correct answer worded
  differently can fail them: that is a limit of the instrument, shown, not hidden.
- **Speed.** Model seconds (time inside model calls) and calls per run, and wall-clock seconds. Wall-clock time mostly
  measures queueing behind the free tier's rate limit, which is shared by every run, so the report labels it and adds
  `limiter s`, the seconds a run's calls take to get through that limit.
- **Tokens.** Prompt and completion separately, per run and per passing run. Prompt tokens are split into the **opening**
  (the first call of every conversation: system prompt, tool list and question; a team opens one conversation per hand-off)
  and **later** (every other call: the conversation so far sent again, plus whatever the step added, so an upper bound on
  re-sent text). Both are counts the provider reported.
- **Cost.** The free tier bills nothing and this project has no price table, so cost is reported without inventing a price:
  in relative units (an input token is 1 unit, an output token is r units, for r = 1, 2, 4, 8 and 20), as the one claim that
  holds for any prices (the cost ratio lies between the input-token ratio and the output-token ratio), and as requests (what
  a free key is spent in: requests a run, and runs in a 500-request day). Dollars appear only when you state both prices and
  where you read them, and are labelled as an assumption.

What the report marks **derived** is worked out from recorded numbers, not measured: the extra prompt tokens a hand-off
that carried the whole conversation would have cost (a lower bound), the prompt tokens the manager spends re-reading the
specialists' answers, and the seconds saved if hand-offs asked for in one step had overlapped.

## A short glossary (terms, not answers)

- **Orchestrator-worker**: one agent (the orchestrator, here the manager) splits the job and hands the pieces to workers
  (here the specialists), then assembles the result.
- **Specialist agent**: an agent given one narrow job, its own instructions and only the tools that job needs.
- **Hand-off**: the manager asking a specialist to do something. In this repository it is an ordinary function call that
  runs another agent loop. What travels is one question and one answer.
- **Context re-send**: a model has no memory between calls, so each call sends the whole conversation again. A hand-off
  starts a new conversation, which is why the report counts opening and later prompt tokens apart.
- **A2A (Agent-to-Agent)**: the brief's definition: "a standard for one agent to hand work to another. MCP connects an
  agent to tools; A2A connects an agent to other agents." A2A is not implemented here. Nothing in this repository speaks it
  and no A2A library is installed.
- **Agent card**: a name the brief lists for a description an agent publishes of itself. `agent_summary` in
  `app/agent/team.py` is a plain summary (name, what it does, its tools) used to word the hand-off tools. It is served nowhere
  and is not in any protocol's format.
- **MCP versus A2A, in this repository**: Week 9's agent discovers tools over MCP; this week's manager reaches a specialist
  through an ordinary in-process `Tool`, neither MCP nor A2A.
- **CrewAI, AutoGen**: agent frameworks. This project does not use them: the loop is hand-written, as it has been since
  Week 7, so our own code counts every token. They are not evaluated here.
- **When multi-agent helps**, in the brief's words: "When parts of the job are truly independent and can run in parallel, or need
  clearly different instructions." Whether that is true of these nine tasks, and what follows from it, is for you to say.

## What is not built

Specialists that run side by side, a network protocol between agents (A2A), more than two specialists, an analyst or verifier
role, a second scorer for the rule checks, and tasks written to favour a team. Each is listed with its reason in `CHANGES.md`.

## The part that is yours

The verdict (which design to keep, and why, in your own words and backed by the numbers), when multi-agent would be worth it
and when it would not, the price you state for the dollars (and where you read it), your reading of every failed run as a
failure of substance or of form, and what result would change your mind. These are blank in `findings.md` on purpose: the brief
asks for your own verdict, and the code and the numbers are not it.
