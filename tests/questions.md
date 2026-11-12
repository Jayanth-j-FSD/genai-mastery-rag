# Test questions (the Week 3 hand-run checklist)

Covers the Week 3 mentor checks against the documents currently in `data/corpus/`. Questions 10
and 11 are deliberately NOT in the documents, to prove the "I don't know" path (check #3).

Every expected answer below was read out of the named file, and
`tests/unit/test_eval_assets.py` fails if one stops being true.

| # | Question | In docs? | Expected source / answer |
|---|----------|----------|--------------------------|
| 1 | How many annual leave days does the Acme leave policy give full-time employees? | yes | Acme-Leave-Policy-2026.md (18) |
| 2 | How many unused leave days can be carried forward under the Acme leave policy? | yes | Acme-Leave-Policy-2026.md (10) |
| 3 | After how many days of service may an employee request remote work? | yes | Northstar-Remote-Work-Policy-2026.md (60) |
| 4 | What is the pension match? | yes | benefits.md (5%) |
| 5 | What does error ERR-4032 mean? | yes | support-faq.md (source connection timed out) |
| 6 | How often must passwords be rotated? | yes | security-policy.md (90 days) |
| 7 | Under the Acme employment terms, how many days of written notice must a permanent employee give? | yes | Acme-Employment-Terms-2026.md (30) |
| 8 | What are the four data classification levels? | yes | Nexora_Tech_Azure_Cloud_Data_Access_Policy.md (Public, Internal, Confidential, Restricted) |
| 9 | What is the standard probation period? | yes | Synthetic_HR_Policy_RAG_Test_Dataset.md (6 months) |
| 10 | Is there an annual bonus scheme? | **NO** | should say "I don't know" |
| 11 | What is Nexora Tech's Azure subscription ID? | **NO** | should say "I don't know" |

Question 8 is list-shaped (four rows of one table) and question 9 is the single real fact in a
section whose other lines are repeated 136 times. They are the two most likely to change when the
chunk size changes, which is what check #4 asks you to notice.

Where the documents disagree (annual leave is 18 in the Acme policy and 24 in the handbook), the
questions above name the company so that one answer is right. A question that does not name one
(see `tests/eval_set.py`, `ambiguous-leave-days`) accepts either number.

## Chunk-size experiment (check #4)
Run each config, ask questions 1-11, note what changes (precision, misses, context):

- **Config A** — CHUNK_SIZE=800, CHUNK_OVERLAP=120
- **Config B** — CHUNK_SIZE=400, CHUNK_OVERLAP=60

Observation A:
Observation B:
Difference noticed:

Tip: `python scripts/compare_chunks.py` runs both configs over questions 1-9 and prints, per
question, whether the expected source was retrieved (and at what rank). It uses the same dense
search the Week 3 app used, so the experiment is the Week 3 one. The written observation above is
the part the mentor grades, and it has to be in your own words.

## Week 4 note

This file stays the Week 3 hand-run checklist and `compare_chunks.py` uses exactly these
questions with the dense search, so that experiment stays reproducible.

Week 4 needed the same idea in a form a script can score, including questions built to fail. That
set lives in `eval_set.py` beside this file, with an expected document and an accepted answer
phrase per question. Use `eval_set.py` for measurements and this file for reading by hand.
