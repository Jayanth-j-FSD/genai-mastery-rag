# TODO — the live checklist

Status legend:  `[ ]` not started · `[~]` in progress · `[x]` done

The delivery plan, rules and per-week status live in [GOAL.md](GOAL.md). This file is the detailed
checklist behind it. Items marked **(you)** are your own work and are deliberately not
automated.

## Weeks 3 to 5: code
- [x] The six-stage pipeline, the FastAPI app, the CLI, trace logging (Week 3)
- [x] Hybrid search, the failure classifier, the inspection view, the eval scripts (Week 4)
- [x] Sampling, the notes gate, grouping and ranking tools (Week 5)
- [x] Offline unit tests for all of it (`tests/unit/`, run by `scripts/check_all.py`)

## Weeks 3 to 5: hardening (branch `week-5-hardening`, see `docs/hardening/README.md`)
- [x] Free-provider support: Gemini answers, local embeddings, the offline model downloader
- [x] Chat calls throttled and retried in one place (`app/llm.py`)
- [x] Dense search made exact; the approximate index kept behind `DENSE_SEARCH=ann`
- [x] Ingest no longer empties the index before embedding; an empty index is an error, not a refusal
- [x] Week 5 "reproduce" command can no longer overwrite the notes; `--upto N` recreates the population
- [x] Provider failures become clear HTTP errors; printing can no longer crash on a Windows console
- [x] Stale test assets rewritten for the current documents; the Nexora answer key moved out of the corpus
- [x] Dependencies pinned, README and `.env.example` rewritten, errata added to the frozen week docs
- [x] `scripts/check_all.py`, the regression gate

## Week 3: run and verify the four mentor checks
- [x] `python scripts/ingest.py` builds the index (9 documents, 432 chunks)
- [x] #1 correct answers from the documents: see `docs/week4/failure-labels-dense.md` for each question's answer
- [x] #2 every answer shows its source document
- [x] #3 an absent topic gets "I don't know" (the refusal cases in the same file)
- [x] #4 the two-size experiment was run: `docs/week3/chunk-experiment.md` has the numbers
- [ ] **(you)** write what changed between the two chunk sizes, in your own words (`tests/questions.md`)

## Week 4: run and fill in the deliverable
- [x] `scripts/diagnose_failures.py --mode dense --save` run: labels with evidence
- [x] `scripts/eval_retrieval.py --save` run: hit-rate@1/@3/@5 and MRR, dense vs hybrid
- [ ] **(you)** fill `docs/week4/findings.md` sections 2 to 6 in your own words (numbers are in the generated files)
- [ ] **(you)** pick one failure and write it out with its evidence (check #1)
- [ ] **(you)** say which failures the change did not fix, and which it broke (check #4)

## Week 5: the analysis itself (the part that cannot be automated)
- [ ] `python scripts/ask_batch.py` builds a population of real traces (about 75 questions, throttled)
- [ ] `python scripts/sample_traces.py --n 20` draws the fair sample (check #1)
- [ ] **(you)** read all 20 traces; fill verdict / note / severity by hand in `worksheet.md` (check #2)
- [ ] `python scripts/code_notes.py` passes only when the reading is genuinely done
- [ ] **(you)** add one group name per failure in `coded-notes.md` (check #3)
- [ ] `python scripts/rank_problems.py --save` produces the ranking (check #4)
- [ ] **(you)** write `docs/week5/taxonomy.md`: groups, ranking, chosen target, and the prediction first

## Later weeks
- [ ] Weeks 6 to 9: see [GOAL.md](GOAL.md); each gets its own branch, tag and `docs/weekN/` folder
- [x] Week 10: built, raced, findings generated (`docs/week10/findings.md`)
- [x] Week 11: built, measured, findings generated (`docs/week11/findings.md`)

## Open decisions (yours)
- [ ] The documents disagree: annual leave is 18 days in the Acme policy and 24 in the handbook and
      `benefits.md`; the notice period is 30 vs 60 days; the learning budget is $1,000 vs INR 30,000.
      The eval set accepts either where the question does not name a company. Decide what the
      corpus should be.
- [ ] Four fictional companies are mixed (Acme, Northstar, Nexora, Northwind); the four Northwind
      sample files are off-track for an HR corpus. Keep them for more Week 5 failures, or remove them.
- [ ] The Excel test workbook (`tests/Week3-Test-Cases.xlsx`) was built for the earlier corpus and its
      Setup sheet predates the free-provider setup. Rebuilding it needs Excel (`tests/sheet-source/`).
