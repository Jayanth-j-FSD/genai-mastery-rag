# Week 6: what changed, and why

The one-page answer to "what did you actually do this week?". Nothing from Weeks 3 to 5 was
rewritten: everything here is a new file or an additive, default-off change.

**Left for you.** The interpretation, the judge grading and the ship decision are blank in `findings.md`.

## The experiment log

Week 6 asks for one improvement and a before-and-after score. The honest way to get there is the Week 5
method: diagnose, hypothesise, change one thing, measure, and write down what happened, including when the
hypothesis was wrong. The three improvement experiments are logged in the order they were run. Two context
runs, `degraded` (4 chunks to 1) and `hybrid` (hybrid search at 4 chunks), were run before experiment 2 was
built, so their results were known when experiments 2 and 3 were designed. Experiment 1 has a hypothesis
recorded with its result; experiments 2 and 3 have predictions that were committed before their runs.

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

- **Hypothesis**: the seven boilerplate lines (each repeated 136 times, under every handbook
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
- **What would prove the hypothesis wrong**: either retrieval case still failing, or any baseline pass failing.

- **Result** (`evals/results/strip.json`): 37 of 41 cases pass the rule checks (90%), **down** from 38 of 41
  (93%). The prediction was right on two of its five points and wrong on three:
  1. `exact-security-email` and `nexora-inactive-accounts` still fail. Wrong.
  2. `nexora-prod-approvals` still fails. Right: it is an incomplete list, not a retrieval failure.
  3. A baseline pass broke: `paraphrase-retirement` now answers "I don't know". Wrong.
  4. The index has 34 chunks. Right.
  5. The score fell from 93% to 90% instead of rising to 98%. Wrong.
- **Why it was wrong**:
  - Stripping helped retrieval, but not enough. `python scripts/screen_retrieval.py` (below) shows the
    security policy moved from "not in the top 10" to 5th, one place outside the four chunks that reach the
    model, and the Nexora inactive-accounts chunk from "not in the top 10" to 8th.
  - The regression is tied to the context, not to a one-off bad reply. In both runs `paraphrase-retirement`
    has the same three leading chunks and the right one at rank 3; only the 4th chunk differs (a
    mostly-headings fragment of the handbook, with two real bullets, replaces a handbook paragraph). A fresh
    call with the strip context returned the genuine refusal "I don't know based on the provided documents."
    (finish reason `stop`, 11 completion tokens, so not an empty reply). A control run of five baseline cases
    with the cache off (`evals/results/noise-check.json`) reproduced all five pass/fail verdicts, but the
    answer wording was identical in only two of the five, so temperature 0 is not exactly deterministic on
    this provider and one repeat bounds the noise only weakly.
  - The two failing questions are hard for dense search by itself, not only crowded out: with the crowding
    gone they still rank 5th and 8th. The boilerplate was hiding that.
- **Verdict**: kept as a default-off setting, **not** the improvement.

### Experiment 3: retrieve with fusion and fetch a little wider (`RETRIEVAL_MODE=hybrid`, `TOP_K=6`)

Written down **before** the run, and committed before the run.

- **A free screen first.** Instead of picking a third change by intuition, `python scripts/screen_retrieval.py` asks a
  cheaper question that needs no model call: under each configuration, does a chunk that holds the answer
  (right document, contains one of the case's fact strings) reach the top k? 37 cases have an answer.

  | configuration | chunks | top 4 | top 6 | top 8 | top 10 |
  |---|---|---|---|---|---|
  | dense (the baseline) | 432 | 35 | 35 | 35 | 35 |
  | dense + strip (experiment 2) | 34 | 35 | 36 | 37 | 37 |
  | hybrid | 432 | 36 | 37 | 37 | 37 |
  | hybrid + strip | 34 | 36 | 37 | 37 | 37 |

  The cases outside the top 4 are `exact-security-email` (dense: not in the top 10; strip: 5th; hybrid: 2nd),
  `nexora-inactive-accounts` (dense: not in the top 10; strip: 8th; hybrid: 1st) and
  `paraphrase-retirement` (dense: 3rd; hybrid: **6th**). Read against the three live runs so far, the screen
  correctly said which cases lose their answer chunk from the context: the baseline loses the first two,
  stripping does not recover them, and hybrid recovers them but pushes the paraphrase case to 6th. What it
  cannot say is whether the model uses a chunk that is present: it counted `paraphrase-retirement` as a hit
  under strip, and the model refused anyway.
- **Hypothesis**: the failures are dense search ranking problems, not only crowding. Hybrid search
  (meaning plus keywords) recovers the two keyword-like cases, and fetching 6 chunks instead of 4 keeps the
  paraphrase case that hybrid pushes to 6th. Neither half works alone: widening dense search to 6 changes
  nothing (35 of 37, from the screen only; it was not run live), and hybrid at 4 still loses one case.
- **Stated now, so it cannot be hidden later**: the cases that motivated this choice are the cases that
  measure it, and the screen was read before choosing. This is a screened choice, not a blind one, so the
  after-score is optimistic. A held-out set is the right next step and is listed in `findings.md`.
- **Prediction** (falsifiable), for `--label wide --set retrieval_mode=hybrid --set top_k=6`:
  1. `exact-security-email`, `nexora-inactive-accounts` and `paraphrase-retirement` pass (their useful
     chunks rank 2, 1 and 6 under hybrid).
  2. `nexora-prod-approvals` still fails: it has failed in every run, and no retrieval change touches an
     incomplete list.
  3. `ambiguous-notice-period`, which hybrid at 4 chunks lost to the judge (it ignored a conflict between
     two documents), passes again, because more chunks make both documents likelier to be present. This one
     is a guess.
  4. At most one baseline pass flips to a failure (a bigger context can change what the model does).
  5. The rule score goes from 38 of 41 (93%) to 40 of 41 (98%), and the strict score (rules and judge) from
     38 of 41 to 40 of 41.
- **What would prove the hypothesis wrong**: a rule score of 38 of 41 or lower, or two or more baseline passes failing,
  or any of the three target cases still failing.

- **Result** (`evals/results/wide.json`): 39 of 41 cases pass the rule checks (95%), **up** from 38 of 41
  (93%), and the strict score (rules and judge together) also goes from 38 to 39 of 41. Two cases were fixed
  and one broke, so the net gain is one case. Against the five-point prediction:
  1. `exact-security-email` and `nexora-inactive-accounts` pass; `paraphrase-retirement` still fails. Half right.
  2. `nexora-prod-approvals` still fails. Right.
  3. `ambiguous-notice-period` passes again. Right (this was a guess).
  4. One baseline pass flipped, `paraphrase-retirement`, within the allowance of one. Right.
  5. 39 of 41, not the predicted 40. Wrong by one.
  By the test written down in advance ("any of the three target cases still failing") the hypothesis is
  **partly refuted**, even though the score went up.
- **By problem type** (`before-after.md`): exact-string 83% to 100%, single-fact 90% to 100%, paraphrase
  100% to 75%, every other type unchanged.
- **Why `paraphrase-retirement` still fails**: the screen said a useful chunk would be in the top 6, and it
  is: `benefits.md` is the sixth and last chunk the model sees, behind five chunks that do not answer the
  question (the first is the handbook's retirement-benefits boilerplate). The model still refused, and a
  fresh call with exactly this context returned the genuine refusal again. Across the runs: it passes with
  the chunk 3rd of 4 (baseline), fails with the chunk 3rd of 4 and a different 4th chunk (strip), and fails
  with the chunk 6th of 6 (wide). Those three contexts cannot separate where the chunk sits from which other
  chunks are present, so the honest reading is only that this model's use of a chunk that is present is
  fragile. A retrieval screen cannot see that; it was labelled necessary, not sufficient.
- **Verdict**: the best of the three experiments and the only one that raised the score, so it is the
  improvement this week reports. It is small and mixed: two fixed, one broken, 41 cases, chosen with the
  failures in view (see the caveat above). Whether to adopt it (`RETRIEVAL_MODE=hybrid` and `TOP_K=6` in
  `.env`) is your decision; the app's defaults are unchanged, and Week 3 is still graded with
  dense search.

## Considered and deferred

| Technique | Why not this week |
|---|---|
| RAGAS metrics (faithfulness, answer relevancy, context precision and recall) | They are the same idea as the judge plus the rule checks, implemented with several model calls per metric per case. On a free tier that is hundreds of calls for no new information, and it adds a dependency. The judge's rubric covers faithfulness and relevance, and the rule checks cover context precision indirectly (right document cited). |
| A 1 to 10 judge score | A pass/fail verdict is easy for a person to agree with, which is what validating a judge needs. A 1 to 10 score drifts and cannot be validated without a rubric for every number. |
| Pairwise (A versus B) judging | Useful for comparing two systems, but this week's question is whether one system passes, and pairwise judging doubles the calls. |
| Each half of experiment 3 alone | Hybrid at 4 chunks was run live (`hybrid.json`): 39 of 41 on the rules but 38 of 41 with the judge, because it also lost `ambiguous-notice-period` to the judge. Widening dense search to 6 chunks was not run live: the screen says it recovers nothing (35 of 37). The hybrid code is Week 4's; this week's contribution is the measurement and the pairing with `TOP_K`. |
| MMR (diversity re-ranking) | A real candidate for the same failure, deferred so that this week stays one change. It was also deferred in Week 4, for a reason that turned out to be wrong for this corpus. |
