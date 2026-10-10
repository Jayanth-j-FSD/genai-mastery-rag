# Week 6: Evals

## The task (from the brief)

You can name the problems now. This week you build the machine that catches them automatically: a set
of test cases that give every future change a score instead of a gut feeling. The task, in the brief's
words: *build a small test set that runs with one command and scores your app's answers. Make one
improvement and show the score went up, with a before-and-after number, per problem type.* The track
line for HR policy: *validate the policy-answer judge before you trust its number.*

In plain words: an eval set is real questions plus a way to score each answer. Simple rule checks come
first because they are free (did it cite the right document? did it refuse when it should have?). An AI
judge grades what a rule cannot (is the answer faithful? did it handle two documents that disagree?),
but only after you have checked that it agrees with your own grading. Then one change is measured,
group by group.

## Definition of done: the mentor's four questions

1. Does the test set run with a single command?
2. Are last week's real failures included as tests?
3. If they used an AI judge, did they check it agrees with their own grading first?
4. Is there a before-and-after score proving the change helped?

## What was built, and which check it serves

| Piece | File | Serves |
|---|---|---|
| The eval set: Week 4's 32 cases plus 9 new Nexora cases, each with a problem type and a human-written reference answer | `evals/cases.py` | 1 |
| Rule checks: cited the right document, refused when it should have (and answered when it should have), contains the facts, no invented numbers | `evals/checks.py` | 1 |
| The AI judge: binary pass/fail with a rubric, reason before verdict, a different model from the answerer | `evals/judge.py` | 3 |
| The runner: a private index per configuration, model calls cached by exact input, stop-and-resume on a quota | `evals/runner.py` | 1, 4 |
| **One command**: `python scripts/run_evals.py` | `scripts/run_evals.py` | 1 |
| Last week's failures turned into permanent tests, problem type = your own group name | `scripts/make_regressions.py` | 2 |
| A blind grading sheet for you, then judge-vs-you agreement and Cohen's kappa | `scripts/make_judge_sheet.py`, `scripts/validate_judge.py`, `evals/validation.py`, `evals/agreement.py` | 3 |
| Before-and-after, per problem type, naming the cases fixed and broken | `scripts/compare_evals.py`, `evals/report.py` | 4 |
| A free retrieval-only screen: does a chunk that holds the answer reach the model? (no model calls) | `scripts/screen_retrieval.py`, `evals/screen.py` | 4 |
| Every saved run as one table | `scripts/list_runs.py` | 4 |
| The improvement experiments, each logged with its prediction: exact-duplicate removal (`DEDUPE_CHUNKS`, no effect), boilerplate stripping (`BOILERPLATE_MIN_REPEATS`, worse), then hybrid search with 6 chunks (the existing `RETRIEVAL_MODE` and `TOP_K` settings, +1 case) | `app/rag/pipeline.py` (`build_chunks`, `strip_repeated_lines`), `docs/week6/CHANGES.md` | 4 |

## Run it

```powershell
.\.venv\Scripts\python.exe scripts\run_evals.py --label baseline
.\.venv\Scripts\python.exe scripts\run_evals.py --label wide --set retrieval_mode=hybrid --set top_k=6
.\.venv\Scripts\python.exe scripts\compare_evals.py baseline wide --save
.\.venv\Scripts\python.exe scripts\list_runs.py             # every saved run as one table
.\.venv\Scripts\python.exe scripts\screen_retrieval.py     # free: does the answer chunk reach the model?
```

`--set NAME=VALUE` changes one setting for one run, so "after" differs from "before" by exactly that
setting. `--no-judge` skips the judge, `--only ID ...` runs chosen cases, `--min-score 0.9` turns a run
into a gate (exit status 2 below the score). Calls are cached by their exact input, so repeating a run
costs nothing for unchanged cases. If a daily quota runs out the run saves what finished and stops;
run it again later to resume.

## The parts that are yours

The brief is explicit that these cannot be automated, so they are built as tools and left blank:

1. **Last week's real failures** (check #2). They come from your Week 5 reading, which has not been
   done. Until it is, `evals/regressions.json` does not exist and the converter is tested against a
   fixture. After you have named your groups in `docs/week5/coded-notes.md`, run
   `python scripts/make_regressions.py`. Every failure becomes a case whose problem type is the group
   name you chose. You then fill in what a correct answer looks like (instructions inside the file).
2. **Grading the judge** (check #3). Run `python scripts/make_judge_sheet.py --runs baseline --n 20`,
   grade the sheet by hand without seeing the judge's verdicts, then `python scripts/validate_judge.py`.
   Until you have, the judge's scores are not evidence: the run output says so.
3. **What the numbers mean** (check #4). `docs/week6/findings.md` has the generated numbers; the
   interpretation, and whether the change helped, are yours to write.

## One improvement, measured honestly

The baseline fails three cases. Two are *retrieval* failures (the Week 4 kind): for "What is
security@northwind.example used for?" and for the Nexora inactive-accounts question, the four chunks that
reach the model are handbook boilerplate, so the model never sees the text that answers. The third is a
generation failure (an incomplete list) that no retrieval change can fix.

The improvement has to target the retrieval mechanism, and the first guess was wrong, which is part of
the record. `docs/week6/CHANGES.md` is the experiment log: each hypothesis, the prediction written before
the run, and what happened. In short:

1. **Drop exact-duplicate chunks** (`DEDUPE_CHUNKS=true`). Predicted to free the crowded slots. It changed
   nothing: the crowding chunks are near-duplicates (a unique heading plus the same boilerplate), not
   exact copies. Kept as a default-off setting and **not** counted as the improvement.
2. **Strip lines repeated many times inside one document** (`BOILERPLATE_MIN_REPEATS=10`). The prediction
   was committed before the run, so the git history shows the order. It was wrong: the score fell from
   38 to 37 of 41 cases, and stripping did not recover the two retrieval failures.
3. **Retrieve with fusion and fetch a little wider** (`RETRIEVAL_MODE=hybrid`, `TOP_K=6`), chosen after a
   free retrieval-only screen (`python scripts/screen_retrieval.py`, no model calls) and again with its
   prediction committed before the run. It is the only experiment that raised the score: 38 to 39 of 41
   cases (93% to 95%), with two cases fixed and one broken, and the prediction was partly wrong. The full
   result is in `CHANGES.md` and the per-problem-type table in `before-after.md`.

Other levers exist and are not the improvement: Week 4's hybrid search (`--set retrieval_mode=hybrid`)
and a larger `TOP_K`. `findings.md` reports them for context only.
