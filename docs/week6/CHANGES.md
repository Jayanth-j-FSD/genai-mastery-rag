# Week 6: what changed, and why

The one-page answer to "what did you actually do this week?". Nothing from Weeks 3 to 5 was
rewritten: everything here is a new file or an additive, default-off change.

## The experiment log

Week 6 asks for one improvement and a before-and-after score. The honest way to get there is the Week 5
method: diagnose, hypothesise, change one thing, measure, and write down what happened, including when the
hypothesis was wrong. Every experiment is logged here in the order it was run.

**The baseline** (`evals/results/baseline.json`, 41 cases, answer model `gemini-3.5-flash-lite`, judge
`gemini-3.1-flash-lite`): 38 of 41 cases pass the rule checks (93%); the judge passes 40 of 41 (98%).
Three cases fail:

| case | what happened | kind |
|---|---|---|
| `exact-security-email` | refused: the security policy was not in the top 4 | retrieval |
| `nexora-inactive-accounts` | refused: the Nexora chunk with the answer was not in the top 4 | retrieval |
| `nexora-prod-approvals` | answered, but listed only some of the five required approvals | generation (an incomplete list) |

In both retrieval failures the four fetched chunks were handbook boilerplate ("### Security /
Northstar Digital Solutions Pvt. Ltd. maintains this policy..."). That is the duplicate crowding that
`docs/week4/CHANGES.md` called "not this corpus's problem", which was true of the original corpus and is
false of this one.

### Experiment 1: drop exact-duplicate chunks (`DEDUPE_CHUNKS=true`)

- **Hypothesis**: the crowding is exact copies (264 of 432 chunks are exact copies of another chunk), so
  removing them frees the slots.
- **Result**: nothing changed. 432 chunks became 180, and the same three cases failed with the same
  reasons (`evals/results/dedupe.json`). 38 of 41 cached answers were reused, which means the retrieved
  context was identical for 38 questions.
- **Why it was wrong**: the chunks that crowd are not exact copies. Each is a unique heading plus the same
  boilerplate, so they are near-duplicates and exact comparison cannot see them.
- **Verdict**: the change is kept as a default-off setting because it is correct for what it does and its
  tests pass, but it did not help here and is **not** the improvement.

### Experiment 2: strip lines repeated many times within a document (`BOILERPLATE_MIN_REPEATS=10`)

Written down **before** the run, and committed before the run, so the history shows the order.

- **Hypothesis**: the seven boilerplate lines (repeated 108 to 136 times under every handbook
  subsection) are noise that makes every handbook chunk look alike to the embedding model. Removing lines
  that repeat at least 10 times inside one document, keeping headings, should leave each subsection as its
  heading plus its real fact, and let the documents that answer outrank the noise.
- **Preview, read-only, before any change**: on the real handbook this takes it from 190,300 to 8,739
  characters and the index from 432 to 34 chunks. The real facts survive (the probation bullet is intact).
- **Prediction** (falsifiable):
  1. `exact-security-email` and `nexora-inactive-accounts` pass after the change.
  2. `nexora-prod-approvals` still fails: it is an incomplete list, not a retrieval failure.
  3. No case that passes at baseline fails after the change.
  4. The index has about 34 chunks.
  5. Overall rule score moves from 93% (38/41) to 98% (40/41), no better, because only two cases can improve.
- **What would prove me wrong**: either retrieval case still failing, or any baseline pass failing.

(Results are added below once the run has happened.)

## Considered and deferred

| Technique | Why not this week |
|---|---|
| RAGAS metrics (faithfulness, answer relevancy, context precision and recall) | They are the same idea as the judge plus the rule checks, implemented with several model calls per metric per case. On a free tier that is hundreds of calls for no new information, and it adds a dependency. The judge's rubric covers faithfulness and relevance, and the rule checks cover context precision indirectly (right document cited). |
| A 1 to 10 judge score | A pass/fail verdict is easy for a person to agree with, which is what validating a judge needs. A 1 to 10 score drifts and cannot be validated without a rubric for every number. |
| Pairwise (A versus B) judging | Useful for comparing two systems, but this week's question is whether one system passes, and pairwise judging doubles the calls. |
| Hybrid search or a larger `TOP_K` as the improvement | Hybrid is Week 4's change; reusing it would not be new work. Both are measured for context in `findings.md`, not chosen. |
| MMR (diversity re-ranking) | A real candidate for the same failure, deferred so that this week stays one change. It was also deferred in Week 4, for a reason that turned out to be wrong for this corpus. |
