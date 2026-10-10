# Week 6: before and after (generated)

Generated 2026-10-11T01:52:30 by `python scripts/compare_evals.py baseline wide --save`. Numbers only: what they mean is yours to write in `findings.md`.

```
=== before 'baseline' vs after 'wide' ===

before : answer gemini-3.5-flash-lite, judge gemini-3.1-flash-lite, 432 chunks, settings as configured
after  : answer gemini-3.5-flash-lite, judge gemini-3.1-flash-lite, 432 chunks, settings {'retrieval_mode': 'hybrid', 'top_k': 6}

problem type               n   before    after   change
absent-topic               4     100%     100%      +0pt
careful-reading            5     100%     100%      +0pt
conflicting-documents      3     100%     100%      +0pt
crowded-handbook           5     100%     100%      +0pt
exact-string               6      83%     100%     +17pt
list-answer                4      75%      75%      +0pt
paraphrase                 4     100%      75%     -25pt
single-fact               10      90%     100%     +10pt
ALL                       41      93%      95%      +2pt

fixed by the change    : 2  ['exact-security-email', 'nexora-inactive-accounts']
BROKEN by the change   : 1  ['paraphrase-retirement']
still failing          : 1  ['nexora-prod-approvals']

How much to trust this: 41 cases in total, so one case moves the overall score by 2.4% and by far more inside a small group. Read the named cases above, not only the percentages.
```
