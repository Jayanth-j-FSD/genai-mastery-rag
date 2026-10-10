# Week 6: findings

This is the file the mentor reads. Every number below was printed by a command, and the command is shown
next to it so it can be run again. The sentences that say what the numbers **mean**, and whether the
change should ship, are blank on purpose (section 5): the brief asks for your judgement, and a number
on its own is not a finding.

## 1. The runs

`python scripts/list_runs.py --markdown`

Counts are cases out of 41, not percentages. "rules" is the free assertion checks, "judge" is the AI
judge's pass count, "both" is the strict score (passed the rules and the judge).

| run | what was changed | chunks | rules | judge | both |
|---|---|---|---|---|---|
| baseline | nothing (the baseline settings) | 432 | 38/41 | 40/41 | 38/41 |
| dedupe | dedupe_chunks=True | 180 | 38/41 | 40/41 | 38/41 |
| strip | boilerplate_min_repeats=10 | 34 | 37/41 | 39/41 | 37/41 |
| degraded | top_k=1 | 432 | 35/41 | 39/41 | 34/41 |
| hybrid | retrieval_mode=hybrid | 432 | 39/41 | 39/41 | 38/41 |
| wide | retrieval_mode=hybrid, top_k=6 | 432 | 39/41 | 39/41 | 39/41 |
| noise-check | nothing (the baseline settings) | 432 | 3/5 | 4/5 | 3/5 |

What each row is: `baseline` is the app as it stands (dense search, 4 chunks). `dedupe`, `strip` and `wide`
are the three improvement experiments in `CHANGES.md`, in the order they were tried. `hybrid` is `wide`
without the wider fetch. `degraded` (4 to 1 chunk) is a deliberately worse app, run to see whether the
eval set notices a worse app and to give the judge bad answers to grade. `noise-check` re-ran five
baseline cases with the cache off to see whether identical input gives identical output (it did, 5 of 5).

Model calls and tokens each run used (from the console output of each run; the saved JSON files were
later regenerated from the cache, which zeroes their usage fields):

| run | model calls | input tokens | output tokens |
|---|---|---|---|
| baseline | 82 | 66,969 | 3,100 |
| dedupe | 6 (38 of 41 answers reused from baseline) | 4,370 | 139 |
| strip | 62 | 57,071 | 2,173 |
| degraded | 82 | 32,582 | 2,601 |
| hybrid | 76 | 64,067 | 2,608 |
| wide | 82 | 90,261 | 3,113 |
| noise-check | 10 | 8,418 | 391 |

`wide` sends 6 chunks instead of 4, and used 35% more input tokens than `baseline` (90,261 against 66,969).

## 2. Before and after, per problem type

`python scripts/compare_evals.py baseline wide --save` writes [before-after.md](before-after.md). The two
runs differ by exactly two settings (`retrieval_mode=hybrid`, `top_k=6`).

| problem type | n | before | after |
|---|---|---|---|
| absent-topic | 4 | 100% | 100% |
| careful-reading | 5 | 100% | 100% |
| conflicting-documents | 3 | 100% | 100% |
| crowded-handbook | 5 | 100% | 100% |
| exact-string | 6 | 83% | 100% |
| list-answer | 4 | 75% | 75% |
| paraphrase | 4 | 100% | 75% |
| single-fact | 10 | 90% | 100% |
| **all** | 41 | **93%** | **95%** |

Fixed: `exact-security-email`, `nexora-inactive-accounts`. Broken: `paraphrase-retirement`. Still failing:
`nexora-prod-approvals` (an incomplete list, a generation failure that no retrieval change touches).

## 3. The four mentor questions: what exists today

| # | Question | State |
|---|---|---|
| 1 | Does the test set run with a single command? | Yes: `python scripts/run_evals.py` (41 cases, rule checks and judge). |
| 2 | Are last week's real failures included as tests? | The 32 Week 4 cases are in. Your own Week 5 failures are **not** yet, because they come from your reading, which has not been done: `python scripts/make_regressions.py` converts them once `docs/week5/coded-notes.md` exists. |
| 3 | Did you check the AI judge agrees with your own grading first? | **Not yet.** A blank blind sheet of 24 answers is in `evals/judge_validation/sheet.md`. Grade it without opening `items.json`, then run `python scripts/validate_judge.py`. Until then the judge's scores are not evidence. |
| 4 | Is there a before-and-after score proving the change helped? | Section 2. Read the caveats in section 4 before leaning on it. |

## 4. What the numbers can and cannot carry (facts about the method)

- 41 cases, so one case is 2.4 points of the overall score. Net change from the improvement: +1 case.
- The change was chosen while looking at the failing cases, and those cases are also what measures it.
  The after-score is therefore optimistic. A set of questions written after the choice is the fix; none exists yet.
- The judge only sees the retrieved context. When retrieval fails and the model honestly refuses, the judge
  can pass that refusal (in the baseline, `exact-security-email` is a rules failure and a judge pass). The
  rule checks, which know the expected document, catch what the judge cannot.
- Every run used one answer model (`gemini-3.5-flash-lite`) and one judge model (`gemini-3.1-flash-lite`).
  Results on other models will differ.
- `paraphrase-retirement` flipped between `baseline` (pass) and `strip` and `wide` (fail) while its answer
  chunk was present in all three contexts, at positions 3, 3 and 6. Where in the context a chunk sits
  changed the outcome for this model.

## 5. Yours to write

What the before-and-after number means, in your own words:

>

Would you ship the change (hybrid search and 6 chunks)? Why, or why not?

>

What the judge validation showed (after you have graded the sheet), and whether you trust the judge:

>

What you would try next:

>
