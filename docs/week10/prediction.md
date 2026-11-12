# Week 10: the prediction, written before the race

Committed after the code and the prompts and before the first race run: `git log` shows the order. The code that checks it is `evals/team_prediction.py`, run by `scripts/check_team_prediction.py LABEL`, and every race result records a hash of that file.

Every prediction is about a measured quantity; none says which design to use. The thresholds below are the ones in
that module, and a test fails if they differ.

Where the numbers come from. Anchor 1: the Week 7 race of the single agent on these nine tasks (`evals/results/race-race.json`):
3.5 model calls and 4,220 tokens a run, 704 of the tokens the opening of its one conversation. Anchor 2: a model of the hand-offs on
that tool mix (`scripts/race_team.py --plan`): 6.1 to 8.4 team calls a run (4 if every task were a single lookup: a manager
call, a search, a researcher answer, a manager answer). The bands below are that range over the single agent's 3.5 calls, 1.7 to 2.4
times, widened on both sides because the model is a guess, not a measurement. Anchor 3: two pilots on 14 questions that are not race tasks
(`evals/results/pilot-1.json`, `pilot-2.json`): the single agent made 2.4 calls and 2,300 tokens a run, the team 4.6 calls and
3,300 tokens a run, so a team call is smaller (about 730 tokens against 980).

Read on the units both arms completed (a unit is a task and a repeat); units where any run ended on a provider problem (an error, a spent quota or an
empty reply) or carried a usage warning, and units where an arm is missing, are dropped and counted:

| | prediction | primary metric |
|---|---|---|
| P1 | the team makes between 1.3 and 3.0 times the single agent's model calls per run, and more of them on at least 7 of the 9 tasks | ratio of mean calls per run |
| P2 | between 0.8 and 2.0 times the single agent's total tokens per run | ratio of mean total tokens per run |
| P3 | between 1.0 and 3.0 times the single agent's model seconds per run | ratio of mean model seconds per run |
| P4 | the calculator is handed work in at least 6 of the 9 runs of the three tasks that need a calculation (`t7-carry-forward-sum`, `t7-notice-end-date`, `t7-leave-end-date`) and in at most 4 of the other 18 | runs with a calculator hand-off |
| P5 | on those three tasks the team passes at least as many runs as the single agent minus 2 | passing runs |
| P6 | over all tasks the team passes at least as many runs as the single agent minus 5 | passing runs |
| P7 | the manager asks for one hand-off at a time in at least 70% of the team's runs | runs with no overlapping hand-offs |
| P8 | the team's opening tokens are at least 1.5 times the single agent's | ratio of mean opening tokens per run |
| P9 | at most 3 team runs and at most 2 single-agent runs end on a limit (steps, tokens, time, a repeated call): a run's own stop reason | runs that ended on a limit |
| P10 | on `t7-unanswerable` the team refuses every time and never needs more than 12 model calls | refusals and calls |

The prediction has FAILED if P1, P2, P3 or P6 does not hold. The others are reported held or not held, with no verdict on the whole.
The thresholds are registered for 9 tasks x 3 repeats, 27 units: a race that is incomplete, or that leaves a different number of usable units, gets a
PARTIAL banner and no verdict. P1, P2, P3 and P8 are compared at the two decimals the report prints. Every analysis not listed here is exploratory.
