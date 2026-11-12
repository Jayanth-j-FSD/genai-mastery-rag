# Week 10: findings

This is the file the mentor reads. Every output below was printed by the command shown above it, so it can be run again (a test runs each command and
compares). The sections marked *Yours to write* are blank on purpose: the brief asks for your own verdict, and nothing else in this folder supplies it.

## 1. The race: the same tests, both designs, four numbers (checks 1 and 2)

The single agent and the team (a manager and two specialists) answered the same nine tasks, three times each, with the same model and the same limits, interleaved,
and every request was recorded by the same instrument. The report prints quality, speed, tokens and cost for each, what each arm was run with, and every run that did not
succeed.

Command: `python scripts/race_team.py --show wk10`

```text
=== Week 10 race 'wk10': 9 task(s) x 3 repeat(s), requested model gemini-3.5-flash-lite ===
arms: agent, team; runs interleaved, the order rotating
limits per run: 8 steps, 40000 tokens, 300.0s (the team shares ONE token and time budget; its step limits are per agent); rate limit 12 calls a minute
agent: memory on, calls per tool cap 0, timeout 300s, max steps 8, prompt sha 99482a2e3d5f, tools search_policies 33aa382afee4, calculate 98ffc522b8a3, add_days 5e84795660ef
team: memory on, calls per tool cap 0, timeout 300s, manager steps 8, researcher steps 8, calculator steps 4, manager prompt sha 27b4ca0d98e2, researcher prompt sha 4f964dab33c1, calculator prompt sha 8f08baaba4ce, hand-off tools ask_policy_researcher 034c84e095c1, ask_calculator 35f207763d5a, researcher tools search_policies 33aa382afee4, calculator tools calculate 98ffc522b8a3, add_days 5e84795660ef
code: git d3a71d3, dirty False, team.py f9028f1e4878, loop.py 412b417ffb41, llm.py 53b3a9365ea7, checks.py c332aceff7db, agent_tasks.py bb66360bb46f, race.py 9758a3c986ab, team_prediction.py 92919924cac5, tree 9bb458634e7a
corpus: 9 files, hashes Acme-Employment-Terms-2026.md cd7149efaa3e, Acme-Leave-Policy-2026.md 88efbcccc912, Nexora_Tech_Azure_Cloud_Data_Access_Policy.md 3ced9d1e0b76, Northstar-Remote-Work-Policy-2026.md 0a2c56b5556f, Synthetic_HR_Policy_RAG_Test_Dataset.md a26bf5fb4eed, benefits.md 82a7f7ed49c0, expenses.md 03277fabd58d, security-policy.md 5884e8ff33e5, support-faq.md 11c1e0ee62da
prediction document (docs/week10/prediction.md): git blob 252407c28df2b957fd6368ceaf297175f79d05b3, recorded when the race started

CAPS      what each agent may use. The team shares ONE token and time budget; its step limits are per agent, so its total number of model calls is not capped as a single agent's is
arm       agent        steps   tokens  timeout  calls per tool  memory
agent     agent            8    40000     300s               0      on
team      manager          8   shared   shared               0      on
team      researcher       8   shared   shared               0      on
team      calculator       4   shared   shared               0      on
search tool, the same for every arm: top_k default 3, passage chars 700, retrieval mode dense

INSTRUMENT   what the per-call records say about how each arm was measured
arm        calls  recorded  retried  wait of retried  errors  total != p+c  cached  reasoning   served by
agent        100     27/27        0             0.0s       0             0       0          0   gemini-3.5-flash-lite
team         184     27/27        0             0.0s       0             0       0          0   gemini-3.5-flash-lite
total != p+c = tokens a provider's own total counts beyond prompt plus completion (hidden thinking, for one): those are NOT in the token numbers below, so a real bill could differ. wait of retried = seconds of rate-limit pauses and back-off in calls that needed more than one attempt (not only the back-off). cached = the part of the prompt served from a cache: those tokens ARE inside the prompt counts below, and a provider may bill them at a lower rate.

QUALITY   success = the run finished AND passed the rule checks
arm       runs   success  rate    95% interval  finished   stop reasons
agent       27     25/27   93%      [77%, 98%]     25/27   {'final': 25, 'max_steps': 2}
team        27     27/27  100%     [88%, 100%]     27/27   {'final': 27}
the 95% interval treats every run as an independent trial, but the repeats of a task are correlated, so it is optimistic
paired by task and repeat (27 pairs): both pass 25, only agent 0, only team 2, neither 0; exact McNemar p = 0.500 over 2 discordant pair(s); this treats the repeats of a task as independent, so it is optimistic
by task (9 tasks): agent passed more of the repeats on 0 tasks, team on 2, the same on 7; exact sign test over the 2 differing task(s) p = 0.500 (the task is the unit here, not the repeat)
a difference is only called when the exact p is below 0.05, and with fewer than 6 discordant pairs it cannot be: at this number of runs a gap of one or two runs is not resolved. Read the by-task line first: the pair line counts the near-copy repeats of a task as separate trials

STOPS     runs that ended on a limit themselves, runs in which any agent hit a limit (a specialist's cap the manager worked around counts here), and runs with provider trouble: the SENSITIVITY section below drops the units that have either
arm        own limit   any agent's limit  provider trouble
agent              2                   2                 0
team               0                   1                 0

SPEED     per run. Model seconds are time inside model calls. Wall seconds include queueing behind the previous run's calls in the shared rate limiter
arm        calls  max  >8  >12  model s mean  median    max  wall s mean  median    max  waiting  limiter s
agent        3.7    8   0    0          10.4     5.8   40.0         16.7    15.2   48.2      6.2       18.5
team         6.8   19   3    2          17.5    12.4   66.5         37.8    36.0  110.5     20.1       34.1
limiter s = calls x 60 / the rate limit: the seconds a run's calls take to get through the limiter, what the free tier charges in time. The team calls the model one agent at a time.

TOKENS    per run, prompt and completion apart. Prompt tokens split into opening + later (measured)
arm        prompt  completion   total  median     max  opening   later  per pass
agent        4455         191    4646    2439   13046      704    3750      5017
team         5274         283    5556    5036   18940     1510    3763      5556
opening = the first call of every conversation (a team opens one per hand-off). later = every other call's prompt: the conversation so far sent again plus whatever the step added, so an upper bound on re-sent text. per pass = total tokens divided by passing runs.
derived: had every hand-off carried the manager's whole conversation, the team would have sent between 144 and 3026 more prompt tokens per run (3% to 57% on top of its 5274): an estimate between a floor (the manager's history only) and a ceiling (its whole prompt, tool list included, which forwarding would not carry), not a lower bound; the measured team hands over only the sub-question
derived: the manager re-reads the specialists' answers on its later calls, at most about 87 prompt tokens per run (memory shortens older tool results, which this does not subtract)

COST      relative units: an input token is 1 unit, an output token is r units. No price is assumed: read the column whose r is nearest the ratio of the output price to the input price you state
arm         r=1 per run   r=2 per run   r=4 per run   r=8 per run  r=20 per run
agent              4646          4837          5219          5983          8275
team               5556          5839          6404          7534         10925
per pass            r=1           r=2           r=4           r=8          r=20
agent              5017          5224          5636          6461          8937
team               5556          5839          6404          7534         10925
team / agent in cost units: r=1 1.20x, r=2 1.21x, r=4 1.23x, r=8 1.26x, r=20 1.32x. Whatever the prices, between 1.18x and 1.48x (input tokens 1.18x, output tokens 1.48x) for one input price and one output price; a cheaper price for cached input is a third price, which this bound does not cover
free-tier cost (derived; requests are what a free key is spent in): agent 3.7 requests a run, 135 runs in a 500-request day; team 6.8 requests a run, 73 runs in a 500-request day
a request is every attempt in the per-call records when they are kept (retries and failed calls included), else the successful calls only. The 500-request day is the lite-model figure measured in Week 8 (docs/week8); the model raced here, gemini-3.5-flash-lite, may allow another number.
DOLLARS   prices: no price stated, so cost is not reported (pass --price-in, --price-out and --price-source to scripts/race_team.py --show)

team / agent:  calls 1.84x, tokens 1.20x, model seconds 1.69x, wall seconds 2.27x (ratios of the arms' means)

THE TEAM, BY AGENT   over 27 run(s)
agent         calls   prompt  completion   tokens  share  model s  hand-offs  calls each
manager          70    54030        4438    58468    39%    200.2          0         n/a
researcher       90    78023        2593    80616    54%    212.3         34         2.6
calculator       24    10337         598    10935     7%     61.2         12         2.0
hand-offs by how they ended: {'calculator:finished': 12, 'researcher:finished': 33, 'researcher:not_finished': 1}
hand-offs by stop reason (agent:state:stop reason): {'calculator:finished:final': 12, 'researcher:finished:final': 33, 'researcher:not_finished:max_steps': 1}
derived: hand-offs the manager asked for in the same step could have overlapped; had they, a run would have taken 0.3 seconds less elapsed time on average (model seconds would not change, and the free tier's rate limiter would serialise the calls anyway) (3 of 27 runs asked for two or more at once)

THE TEAM, BY TASK   mean hand-offs and model calls per run
task                    shape         researcher calculator  calls: mgr   res  calc
t7-single-lookup        single               1.0        0.0         2.0   2.0   0.0
t7-carry-forward-sum    dependent            1.0        1.0         3.0   2.3   2.0
t7-notice-end-date      dependent            1.0        1.0         3.0   2.7   2.0
t7-leave-end-date       dependent            1.0        1.0         3.0   2.0   2.0
t7-remote-eligibility   single               1.0        1.0         3.0   2.3   2.0
t7-two-documents        independent          2.0        0.0         2.0   4.0   0.0
t7-conflict             independent          1.0        0.0         2.0   2.0   0.0
t7-cloud-two-sections   independent          1.0        0.0         2.0   2.0   0.0
t7-unanswerable         single               2.3        0.0         3.3  10.7   0.0

PER TASK  shape, then successes out of runs, mean calls, mean tokens; last column team / agent in tokens
task                    shape             agent ok calls  tokens      team ok calls  tokens   ratio
t7-single-lookup        single                3/3    2.0    1881         3/3    4.0    2995   1.59x
t7-carry-forward-sum    dependent             2/3    6.3    9599         3/3    7.3    5586   0.58x
t7-notice-end-date      dependent             3/3    4.3    5284         3/3    7.7    6058   1.15x
t7-leave-end-date       dependent             3/3    6.0    7559         3/3    7.0    5260   0.70x
t7-remote-eligibility   single                3/3    2.3    2651         3/3    7.3    5496   2.07x
t7-two-documents        independent           3/3    2.0    2426         3/3    6.0    4716   1.94x
t7-conflict             independent           3/3    2.0    2077         3/3    4.0    3227   1.55x
t7-cloud-two-sections   independent           3/3    2.0    2100         3/3    4.0    3298   1.57x
t7-unanswerable         single                2/3    6.3    8234         3/3   14.0   13371   1.62x

BEHAVIOUR   what the answers and paths look like, apart from the rule checks
arm        answer chars  documents cited  refused  refused, no search  answered, no hand-off  duplicate searches
agent               471              1.3        2                   0                    n/a                0.00
team                361              1.2        3                   0                      0                0.00

PATH   (exploratory) Week 8's path grader, offline, with the manager's hand-off calls dropped. It was written for ONE agent, so a mode can be a side effect of the split
arm       runs  right, right path  right, wrong path  wrong, right path  wrong, wrong path   modes (runs showing each)
agent       27                 21                  4                  0                  2   {'over-calling': 5, 'loop': 3, 'no-answer': 2, 'skipped-tool': 1}
team        27                 23                  4                  0                  0   {'over-calling': 3, 'made-up-input': 1}

SENSITIVITY   the same comparison with every unit dropped in which any agent of either arm hit a limit or a provider problem (an error, a spent quota or an empty reply) (24 of 27 units kept: 3 dropped for limits, 0 for the provider, 0 incomplete)
arm       runs   success  rate    95% interval  finished   stop reasons
agent       24     24/24  100%     [86%, 100%]     24/24   {'final': 24}
team        24     24/24  100%     [86%, 100%]     24/24   {'final': 24}
paired by task and repeat (24 pairs): both pass 24, only agent 0, only team 0, neither 0; exact McNemar p = 1.000 over 0 discordant pair(s); this treats the repeats of a task as independent, so it is optimistic
by task (9 tasks): agent passed more of the repeats on 0 tasks, team on 0, the same on 9; exact sign test over the 0 differing task(s) p = 1.000 (the task is the unit here, not the repeat)
team / agent on these units:  calls 1.83x, tokens 1.18x, model seconds 1.68x

FAILED RUNS   every run that did not succeed (2)
  t7-carry-forward-sum    agent    repeat 1  stopped: max_steps
      failed checks: refused a question the documents do answer; cited nothing, expected one of ['Acme-Leave-Policy-2026.md']; missing required phrase(s): ['10', '15']
  t7-unanswerable         agent    repeat 3  stopped: max_steps

Read before quoting a number: this is one model on one day and one run of the race, so variation between races is not measured. Each arm has 27 runs and the repeats of a task are correlated, so quality is described, not ranked: a gap smaller than the intervals and the McNemar p allow is not resolved, and with the single agent near the ceiling only a loss can show. The team and the single agent differ in more than one thing (prompts, the split of tools, a manager that must rephrase the question, per-agent step limits), so this compares THIS team with the Week 7 agent as it stands, not multi-agent with single-agent in general. With a rate limit of 12 calls a minute, wall-clock time is mostly the shared rate limiter, and a timeout is probably the limiter unless model seconds alone exceed the budget. Parallel hand-offs were not tried. Tokens are the provider's own counts. Dollars are only as good as the prices you state. The verdict is yours to write in docs/week10/findings.md.
```

## 2. The prediction, written before the race

`docs/week10/prediction.md` was committed after the code and before the first race run; the race script refuses to start unless it is committed and unchanged. This is that
prediction checked against the numbers above, as arithmetic.

Command: `python scripts/check_team_prediction.py wk10`

```text
=== Week 10 prediction, checked against race 'wk10' ===
prediction document recorded with this race: git blob 252407c28df2b957fd6368ceaf297175f79d05b3
read on 27 of 27 units (0 dropped for a provider problem, 0 incomplete; units that hit a limit stay in, P9 counts them)

P1  held     the team makes 1.3 to 3.0 times the single agent's model calls per run, and more on at least 7 of the 9 tasks
             1.84x (band 1.3 to 3.0; compared at the two decimals shown); more calls on 9 of 9 tasks (needs 7)
P2  held     the team uses 0.8 to 2.0 times the single agent's total tokens per run
             1.20x (band 0.8 to 2.0; compared at the two decimals shown)
P3  held     the team spends 1.0 to 3.0 times the single agent's model seconds per run
             1.69x (band 1.0 to 3.0; compared at the two decimals shown)
P4  held     the calculator is handed work in at least 6 of the 9 calculation-task runs and at most 4 of the other 18
             calculator handed work in 9 of 9 runs of the calculation tasks (needs at least 6) and in 3 of 18 other runs (at most 4)
P5  held     on the three calculation tasks the team passes at least as many runs as the single agent minus 2
             team 9, single agent 8 passes on the calculation tasks (team needs at least 6)
P6  held     over all tasks the team passes at least as many runs as the single agent minus 5
             team 27, single agent 25 passes (team needs at least 20)
P7  held     the manager asks for one hand-off at a time in at least 70% of the team's runs
             24 of 27 team runs (88.9%; needs 70%)
P8  held     the team's opening tokens are at least 1.5 times the single agent's
             2.14x (needs at least 1.5x; compared at the two decimals shown)
P9  held     at most 3 team runs and at most 2 single-agent runs end on a limit
             team 0 (at most 3), single agent 2 (at most 2); a run counts when its own stop reason is a limit, and 1 more team run(s) had a hand-off stop on a limit and ended another way (not counted)
P10 NOT HELD on the unanswerable task the team refuses every time with at most 12 model calls
             refused 3 of 3, most model calls in one run 19 (at most 12)

The prediction as a whole: did not fail (it fails if any of P1, P2, P3, P6 does not hold).
Every analysis not listed here is exploratory. The verdict about which design to use is yours to write in findings.md.
```

## 3. The verdict (check 3)

**Yours to write:** which design you would keep and why, in your own words, backed by the numbers above, even if the team lost. A gap smaller than the intervals and the
McNemar p allow is not resolved: say so if that is what the numbers show.

## 4. When multi-agent is worth it, and when it is not (check 4)

**Yours to write.** The brief's own condition, for you to apply: "When parts of the job are truly independent and can run in parallel, or need clearly different
instructions." Whether that is true of these nine tasks, and what follows from it, is yours to say, with the per-task table above as evidence.

## 5. The failed runs

**Yours to write:** for each run listed under FAILED RUNS above, whether it is a failure of substance (the answer is wrong or missing) or of form (a correct answer the rule
checks could not recognise), and why you think so. The rule checks match words, so a correct answer worded differently can fail them.

## 6. The price, and what would change your mind

**Yours to write:** the prices you state for dollars (`--price-in`, `--price-out`) and where you read them (`--price-source`), and what result would change your verdict.

## 7. What was not verified

- One model on one day, three repeats of nine tasks: variation between races is not measured.
- The rule checks are the only scorer (an LLM judge was not used); a correct answer worded differently can fail them.
- The team and the single agent differ in more than one thing (prompts, the split of tools, a manager that must rephrase the question, per-agent step limits), so this compares
  THIS team with the Week 7 agent as it stands, not multi-agent with single-agent in general.
- Wall-clock time is mostly queueing in the free tier's rate limiter; model seconds and the limiter seconds are printed beside it.
- Nothing here was measured against a real price; the dollar figures are yours to add.
