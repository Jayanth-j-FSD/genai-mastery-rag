# Week 7: the race (generated)

Generated 2026-10-11T03:15:43 by `python scripts/race_agent.py --show race --rescore --save`. Numbers only: which approach to ship, and why, is yours to write in `findings.md`.

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
