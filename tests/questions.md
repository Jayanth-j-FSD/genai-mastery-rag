# Test questions (mini eval set for the sample corpus)

Covers all four mentor checks. Questions 8 and 9 are deliberately NOT in the docs,
to prove the "I don't know" path (check #3). Swap these for your real track's
questions when you replace the sample documents.

| # | Question | In docs? | Expected source / answer |
|---|----------|----------|--------------------------|
| 1 | How many annual leave days do full-time employees get? | yes | annual-leave.md (24) |
| 2 | How many unused leave days can carry over to next year? | yes | annual-leave.md (5) |
| 3 | How many days a week can I work remotely? | yes | remote-work.md (3) |
| 4 | What is the pension match? | yes | benefits.md (5%) |
| 5 | What does error ERR-4032 mean? | yes | support-faq.md (source timeout) |
| 6 | How often must passwords be rotated? | yes | security-policy.md (90 days) |
| 7 | What is the daily meal limit while travelling? | yes | expenses.md ($40) |
| 8 | What is the company's parental leave policy? | **NO** | should say "I don't know" |
| 9 | How many sick days do employees get? | **NO** | should say "I don't know" |
| 10 | What is the data retention on the Pro plan? | yes | support-faq.md (36 months) |

## Chunk-size experiment (check #4)
Run each config, ask questions 1-10, note what changes (precision, misses, context):

- **Config A** — CHUNK_SIZE=800, CHUNK_OVERLAP=120
- **Config B** — CHUNK_SIZE=400, CHUNK_OVERLAP=60

Observation A:
Observation B:
Difference noticed:

Tip: `python scripts/compare_chunks.py` runs both configs over these questions and
prints, per question, whether the expected source was retrieved (and at what rank).

## Week 4 note

This file stays as it is — it is the Week 3 hand-run checklist and `compare_chunks.py`
still uses exactly these questions and the Week 3 dense search, so that experiment stays
reproducible.

Week 4 needed the same idea in a form a script can score, including questions built to
fail. That set lives in `eval_set.py` beside this file, with an expected document and an
accepted answer phrase per question. Use `eval_set.py` for measurements and this file for
reading by hand.
