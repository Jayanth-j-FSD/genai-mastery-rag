# Week 7: findings

This is the file the mentor reads. Every number below was printed by a command, and the command is shown
next to it so it can be run again. Which approach you would ship, and why, is blank on purpose (section 4):
the brief asks for your judgement, and a table is not a decision.

## 1. The race

Raced with `python scripts/race_agent.py --label race --repeats 3 --save` on `gemini-3.5-flash-lite`
(limits for the agent: 8 steps, 40,000 tokens, 120 seconds), saved in `evals/results/race-race.json`.
Re-print it for free with `python scripts/race_agent.py --show race`.

```
=== race 'race': 3 run(s) of 9 task(s), model gemini-3.5-flash-lite ===

approach   runs  success  finished  calls avg  tokens avg  model s avg  model s p95
agent        27    26/27      26/27         3.5        4220          3.0          6.5
workflow     27    27/27      27/27         1.0        1177          1.3          1.7

stop reasons: agent: {'final': 26, 'max_steps': 1}; workflow: {'final': 27}

task                           agent ok  calls  tokens  workflow ok  calls  tokens
t7-single-lookup                   3/3     2.0    1895         3/3     1.0     995
t7-carry-forward-sum               2/3     5.3    7770         3/3     1.0    1234
t7-notice-end-date                 3/3     3.0    3239         3/3     1.0    1354
t7-leave-end-date                  3/3     6.0    7679         3/3     1.0    1395
t7-remote-eligibility              3/3     2.3    2504         3/3     1.0    1251
t7-two-documents                   3/3     2.7    3149         3/3     1.0    1306
t7-conflict                        3/3     2.0    2074         3/3     1.0    1032
t7-cloud-two-sections              3/3     2.0    2042         3/3     1.0    1180
t7-unanswerable                    3/3     6.0    7626         3/3     1.0     851

success = finished AND passed the rule checks. 'model s' is time inside model calls: waiting for the free tier's rate limit is excluded. p95 over so few runs is close to the maximum.
The decision about which to ship, and why, is yours: write it in docs/week7/findings.md.
```

Facts read off that table and the saved runs:

- **Reliability.** The agent succeeded on 26 of 27 runs and the fixed workflow on 27 of 27. The agent's one
  failure was the first run of `t7-carry-forward-sum`: it searched eight times with different wordings
  (several naming the handbook or Northstar) without finding what it wanted, never called `calculate`, hit
  the step limit and stopped with no answer.
- **Cost.** The agent made 3.5 model calls per run and used 4,220 tokens; the workflow made 1 call and used
  1,177 tokens. The agent used 3.6 times the tokens.
- **Speed.** Seconds spent inside model calls: 3.0 for the agent, 1.3 for the workflow (p95 6.5 and 1.7).
  Waiting for the free tier's rate limit is excluded from both.
- **Where the agent costs most.** `t7-leave-end-date` and `t7-unanswerable` took 6.0 calls on average and
  `t7-carry-forward-sum` 5.3, against 2.0 for the one-lookup and the conflict tasks. On the unanswerable
  question the agent searched four to seven times before saying "I don't know"; the workflow said it after its one search.
- **Tools.** Whether the agent used `add_days` and `calculate` where a task needed them is not graded this
  week. Week 8 grades the path.

## 2. The four mentor questions: what exists today

| # | Question | State |
|---|---|---|
| 1 | Does the agent complete a genuinely multi-step task, with the steps visible? | Yes. [example-run.md](example-run.md) is a real run with five tool calls (two searches, two date calculations and a saved note) and a cited answer, printed step by step by `scripts/run_agent.py`. |
| 2 | Does it stop safely instead of looping forever? | Four stop conditions (steps, tokens, time, repeated call), each forced by a unit test. [example-stop.md](example-stop.md) shows a real stop on the step limit, and the race's one failure ended the same way: stopped, named, no pretending. |
| 3 | Did you compare it against a plain fixed sequence with real numbers? | Section 1. |
| 4 | Can you say which one you would ship, and why? | Blank: section 4. |

## 3. What the numbers can and cannot carry (facts about the method)

- 27 runs per approach on 9 tasks, so one failed run is 3.7 points. The p95 over so few runs is close to the
  maximum.
- The workflow is the simplest honest recipe (retrieve once, answer once, do any arithmetic in the model's
  head). A smarter fixed chain (one search per sub-question, then a calculator step) is a fairer competitor
  and is deferred in `CHANGES.md`. On these tasks the model does small sums and date arithmetic correctly
  without a tool, so the agent's exact tools did not change an answer here.
- Success is decided by rule checks (the right document cited, the expected facts present, a refusal when the
  documents cannot answer). An answer worded in a way those checks do not accept would count as a failure.
- Both approaches used the same model and the same settings. Other models will differ.
- The nine tasks were written for this race and each expected fact is checked against the documents by a unit
  test. They are not a sample of real questions.

## 4. Yours to write

Which would you ship for this HR assistant, and why? Say what you weighed:

>

What result would change your mind?

>
