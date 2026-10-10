# Week 7: findings

This is the file the mentor reads. Every number below was printed by a command, and the command is shown
next to it so it can be run again. Numbers that were worked out from those printed numbers are marked
"(derived)" with the sum. Which approach you would ship, and why, is blank on purpose (section 5): the brief
asks for your judgement, and a table is not a decision.

## 1. The race

Raced with `python scripts/race_agent.py --label race --repeats 3 --save` on `gemini-3.5-flash-lite`, with
`RETRIEVAL_MODE=dense` for both approaches (limits for the agent: 8 steps, 40,000 tokens, 120 seconds). The raw
runs, including every step, are in `evals/results/race-race.json`. Re-print both views below for free (no model
calls) with `python scripts/race_agent.py --show race --rescore`; section 2 says why there are two.

```
AS RACED (the checks as they were when the race ran):

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

==============================================================================
RE-SCORED with the current checks and tasks (same runs, same answers, no model calls):

=== race 'race': 3 run(s) of 9 task(s), model gemini-3.5-flash-lite ===

approach   runs  success  finished  calls avg  tokens avg  model s avg  model s p95
agent        27    25/27      26/27         3.5        4220          3.0          6.5
workflow     27    24/27      27/27         1.0        1177          1.3          1.7

stop reasons: agent: {'final': 26, 'max_steps': 1}; workflow: {'final': 27}

task                           agent ok  calls  tokens  workflow ok  calls  tokens
t7-single-lookup                   3/3     2.0    1895         3/3     1.0     995
t7-carry-forward-sum               2/3     5.3    7770         3/3     1.0    1234
t7-notice-end-date                 3/3     3.0    3239         3/3     1.0    1354
t7-leave-end-date                  3/3     6.0    7679         3/3     1.0    1395
t7-remote-eligibility              3/3     2.3    2504         3/3     1.0    1251
t7-two-documents                   3/3     2.7    3149         0/3     1.0    1306
t7-conflict                        2/3     2.0    2074         3/3     1.0    1032
t7-cloud-two-sections              3/3     2.0    2042         3/3     1.0    1180
t7-unanswerable                    3/3     6.0    7626         3/3     1.0     851

success = finished AND passed the rule checks. 'model s' is time inside model calls: waiting for the free tier's rate limit is excluded. p95 over so few runs is close to the maximum.
The decision about which to ship, and why, is yours: write it in docs/week7/findings.md.

4 run(s) changed result:
  t7-two-documents        workflow  run 1  pass -> FAIL
  t7-two-documents        workflow  run 2  pass -> FAIL
  t7-two-documents        workflow  run 3  pass -> FAIL
  t7-conflict             agent     run 3  pass -> FAIL
```

Facts read off those tables and the saved runs:

- **Reliability, as raced.** The agent succeeded on 26 of 27 runs and the fixed workflow on 27 of 27.
- **Reliability, re-scored.** Under the stricter checks of section 2 the same runs give agent 25 of 27 and
  workflow 24 of 27, so the totals flip by one run. On `t7-two-documents` the re-score favours the agent (3 of 3
  against 0 of 3), and on `t7-conflict` it moves from a tie to the workflow ahead (3 of 3 against 2 of 3).
- **The agent's one unfinished run** was the first run of `t7-carry-forward-sum`. It searched eight times with
  different wordings (several naming the handbook or Northstar), never called `calculate`, hit the step limit
  and stopped with no answer. Seven of its eight search results contained the sentence it needed ("Employees
  may carry forward up to 10 unused annual-leave days into the next ..."); it kept searching anyway.
- **Cost.** The agent made 3.5 model calls per run and used 4,220 tokens; the workflow made 1 call and used
  1,177 tokens. The agent used 3.6 times the tokens (derived: 4,220 / 1,177).
- **Speed.** Seconds spent inside model calls: 3.0 for the agent and 1.3 for the workflow, 2.4 times as long
  (derived from the unrounded means, 3.02 / 1.27); p95 6.5 and 1.7. Waiting for the free tier's rate limit is excluded from both.
- **Where the agent costs most.** `t7-leave-end-date` and `t7-unanswerable` took 6.0 calls on average and
  `t7-carry-forward-sum` 5.3, against 2.0 for the one-lookup and the conflict tasks. On the unanswerable question
  the agent searched 4, 7 and 4 times before saying "I don't know"; the workflow said it after its one search.
- **The refusals were real.** All six "I don't know" answers (three per approach) came from a final step of 11
  completion tokens, the length of the refusal sentence, so none was an empty reply counted as a refusal.
- **Tools.** Whether the agent used `add_days` and `calculate` where a task needed them is not graded this
  week. Week 8 grades the path.

## 2. Why there are two scores

The first race was scored with rule checks that were too lenient for two tasks, which a closer look at
the branch found. `t7-two-documents` asks for a fact from each of two documents, but the check accepted an answer
that cited either one, and its fact phrases were the bare digits `7` and `12`, which any answer containing those
digits satisfied. `t7-conflict` asks for both
sides of a disagreement, but accepted one cited document. The checks now require every expected document to be
cited (`require_all_sources`) and the phrases `7 calendar days` and `12 paid`, matched as whole words
(`whole_words`, on every Week 7 task), so `17 calendar days` no longer satisfies `7 calendar days`.

Nothing was run again. `race.rescore` recomputes success for every stored run from its stored answer and steps,
under the current checks, and lists each run whose result changed. Both views are in `race-results.md`.

The four runs that changed, read from the saved answers:

- `t7-two-documents`, workflow, runs 1 to 3: every answer says the Acme leave policy has no sick-leave figure
  (one run also cites only one document). The workflow's single retrieval did not fetch that passage. The answers
  do mention a 12-day sick-leave figure, but attribute it to the handbook, not to the Acme leave policy the
  question names. A rule check cannot judge whether that counts as an answer; the three answers are in
  `evals/results/race-race.json` for anyone who wants to read them.
- `t7-conflict`, agent, run 3: the answer states 18 days for the Acme policy but cites `Acme-License-Policy-2026.md`,
  which is not a document. The figure is right and the citation is wrong; the first scorer ignored the invented
  name because another expected document was cited.

## 3. The four mentor questions: what exists today

| # | Question | State |
|---|---|---|
| 1 | Does the agent complete a genuinely multi-step task, with the steps visible? | Yes. [example-run.md](example-run.md) is a real run with six tool calls (four searches and two date calculations) and a cited answer, printed step by step by `scripts/run_agent.py`. |
| 2 | Does it stop safely instead of looping forever? | Four limits (steps, tokens, time, repeated call) and two more endings that never become answers (a provider error, an empty reply), each forced by a unit test. [example-stop.md](example-stop.md) shows a real stop on the step limit, and the race's one unfinished run ended the same way: stopped, named, no pretending. |
| 3 | Did you compare it against a plain fixed sequence with real numbers? | Sections 1 and 2. |
| 4 | Can you say which one you would ship, and why? | Blank: section 5. |

## 4. What the numbers can and cannot carry (facts about the method)

- 27 runs per approach on 9 tasks, so one run is 3.7 points (derived: 1 / 27). The p95 over so few runs is close
  to the maximum. The race was run once, so the variation between whole races is not measured.
- The two approaches do not look at the documents the same way. The workflow's one retrieval returns 6 passages
  whole. The agent's `search_policies` returns 3 by default (up to 6 if it asks), each cut at 700 characters. The
  race compares two designs, not one changed variable.
- The workflow is the simplest honest recipe (retrieve once, answer once, do any arithmetic in the model's head).
  A smarter fixed chain (one search per sub-question, then a calculator step) is a fairer competitor and is
  deferred in `CHANGES.md`.
- The workflow passed the three arithmetic and date tasks (`t7-carry-forward-sum`, `t7-notice-end-date`,
  `t7-leave-end-date`) 3 of 3 each, without a calculator. That suggests, but does not prove, that the model's
  own sums were not the weak point on these tasks; the checks look only at the final figures, not at how they
  were reached.
- Success is decided by rule checks (the right documents cited, the expected phrases present, a refusal when the
  documents cannot answer). An answer worded in a way those checks do not accept counts as a failure, and section 2
  shows the verdict depends on how strict the checks are.
- Both approaches used the same model, `gemini-3.5-flash-lite`. The two example runs used `gemini-3.5-flash` and
  `gemini-3-flash-preview`, because the first model's free daily quota was used up by the time they were captured.
  Other models will differ.
- The nine tasks were written for this race. The sentences their answers are built from are checked against the
  documents by a unit test, and the figures worked out from them are checked against the tools. They are not a
  sample of real questions.
- In the committed race, 24 of the 27 workflow search calls were recorded with their arguments as a Python repr
  (single quotes), not JSON, because the recording code was fixed afterwards. Code that reads those arguments must
  not assume they parse as JSON.
- An empty model reply used to be recorded as "I don't know". It now ends the run as `empty_reply`, so it can no
  longer pass for a refusal. None of the six refusals in this race was an empty reply (section 1).

## 5. Yours to write

Which would you ship for this HR assistant, and why? Say what you weighed:

>

What result would change your mind?

>
