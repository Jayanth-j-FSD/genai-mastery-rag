# Hardening: what changed after the Week 3 to 5 tags, and why

Branch `week-5-hardening`, tagged `week-5-hardened` once `python scripts/check_all.py` passes. The
tags `week-3`, `week-4` and `week-5` are untouched and still show the code as it was built.

## Why this exists

Weeks 3 to 5 were written on a machine with no Python and no API key, so none of it had ever run.
The first real run, on the real corpus, found problems that would make a reviewer's first run
fail or mislead. A read of every file and all three briefs found
more, and a second pass over the fixes themselves found a few more. This branch fixes them without changing the meaning of any
documented function: the Week 3 `retrieve()` still means "the nearest chunks by meaning", it now
actually returns them.

## What was fixed

| Problem | How it showed | Fix | Where it is verified |
|---|---|---|---|
| The app could only run on a paid OpenAI key | no key, no run | `OPENAI_BASE_URL`, local embeddings, `scripts/download_model.py` | `tests/unit/test_local_embedder.py`, README quick start |
| **Dense search missed the right chunk and varied run to run** | "How much notice must a permanent employee give?" answered "I don't know" twice, with four copies of the handbook boilerplate retrieved instead of the Acme policy | `store.query` is exact by default (`DENSE_SEARCH=ann` keeps the old index) | `tests/unit/test_store_search.py`, `scripts/compare_ann_exact.py` (below) |
| Free-tier chat limit (about 5 a minute) broke batches; SDK retries burned the allowance unseen | 429 after the third question | `app/llm.py`: limiter, retries that honour "retry in 51s", daily quota fails clearly, timeout, usage counters | `tests/unit/test_llm.py` |
| **Ingest deleted the index before embedding** *(review P2)* | a failed embed left it empty; every question then answered "I don't know", which looks exactly like a passing check 3 | embed first, then reset; asking an empty index is an error that says "run ingest" | `tests/unit/test_config_pipeline_api.py` |
| **The "reproduce this sample" command could wipe the handwritten notes** *(review P1)* | it carried `--force`, and it could not reproduce the draw once more traces existed | it now writes to a separate file and uses `--upto N` to recreate the population | `tests/unit/test_week5_tools.py` |
| Provider failures were a traceback or a bare 500 *(review)* | a 429 or 401 in `/docs` | 429 for rate limit or daily quota, 502 for provider failure, 400 for our own errors | `tests/unit/test_config_pipeline_api.py` |
| A citation naming two documents lost both *(review)* | `[source: A.md, B.md]` fell back to listing every retrieved document | split on `,` and `;` | `tests/unit/test_generator.py` |
| Traces recorded the wrong model *(review)* | `embed_model` was a setting, not what ran; an alias hides the real model | traces also record `embed_provider`, `dense_search` and the model that answered | `tests/unit/test_config_pipeline_api.py` |
| A bad `CHUNK_OVERLAP` passed startup and crashed mid-ingest *(review)* | `chunk_overlap >= chunk_size` | validated when settings load | `tests/unit/test_config_pipeline_api.py` |
| `EMBED_RPM` below 10 could not be honoured *(review)* | batches were always 10 | batches never exceed the allowance | code review |
| `--out` on another drive crashed the Week 5 scripts | `os.path.relpath` raises on Windows | `display_path` helper | `tests/unit/test_console.py` |
| A character the console cannot show crashed a script after the answer was paid for *(review)* | `→`, `≥` under Git Bash | `make_output_safe` | `tests/unit/test_console.py` |
| A failed restore at the end of the chunk experiment was swallowed *(review)* | it printed "Index restored" regardless | it says so and exits non-zero | code review |
| Traces from before Week 4 were all filed as `## trace ?` *(review)* | no `trace_id` | filed by log line number | `tests/unit/test_week5_tools.py` |
| Dead code | `embedder._get_local()` referred to a downloader the project does not use | removed | |
| **Test assets pointed at deleted documents** | cases for `annual-leave.md` and `remote-work.md`, which the corpus no longer has; three "refusal" cases that the new documents answer | rewritten, see below | `tests/unit/test_eval_assets.py` |
| **The Nexora policy carried its own answer key** | the two hallucination questions could be "refused correctly" by reading the key | moved verbatim to `tests/nexora_eval_questions.md` | `tests/unit/test_eval_assets.py` |
| Docs described an OpenAI-only app that had never run, and `.env.example` set Week 4's search | a fresh clone could not follow the README | README, `.env.example`, pinned `requirements.txt`, overview, project-info, TODO | `pip install --dry-run` against the pins |
| No single answer to "is anything broken?" | | `scripts/check_all.py` | it fails on a planted syntax error and a planted bad import |

## Evidence: approximate vs exact search

`python scripts/compare_ann_exact.py` asks every question in `tests/trace_questions.txt` twice, with
Chroma's approximate index and with an exact search over the same stored vectors, and counts how
often they disagree. The approximate index is rebuilt in memory each time the program starts, so each
run is a new draw.

Every run below is appended to [ann-vs-exact.md](ann-vs-exact.md) by `--save`, so the numbers can be checked
against the committed file and re-run with the same command. All on 2026-10-11, 432 chunks, local
embeddings, the 74 questions in `tests/trace_questions.txt`, k = 4.

**Chroma's default approximate index**, three separate runs:

| run | top-1 chunk differs from exact | top-4 set differs from exact | mean overlap@4 |
|---|---|---|---|
| 1 | 38 of 74 (51%) | 48 of 74 (65%) | 0.500 |
| 2 | 21 of 74 (28%) | 32 of 74 (43%) | 0.730 |
| 3 | 49 of 74 (66%) | 57 of 74 (77%) | 0.341 |

**A tuned approximate index** (`--ef-search 500`, a throwaway copy with a wider search, the usual first
thing to try), three more runs:

| run | top-1 chunk differs from exact | top-4 set differs from exact | mean overlap@4 |
|---|---|---|---|
| 1 | 0 of 74 (0%) | 5 of 74 (7%) | 0.970 |
| 2 | 4 of 74 (5%) | 14 of 74 (19%) | 0.932 |
| 3 | 0 of 74 (0%) | 4 of 74 (5%) | 0.970 |

Exact search returns the same answer every time, so it has no such table: its overlap with itself is
1.000. Two things stand out. The default index was not just inaccurate, it was unpredictable (28% to 66%
of top results wrong between runs), which is the worst property for something a reviewer runs once.
And tuning helps a great deal without ever reaching exact: the top-4 set still differed on 5% to 19% of
questions. Only exact search is deterministic, and at this size it costs milliseconds. One concrete
case: "How far in advance do I have to request leave?" loses the Acme leave policy entirely under the
approximate search and finds it at rank 2 under exact search.

The likely cause is that identical vectors (264 of the 432 chunks are exact copies) mislead the graph
search, and that the index is rebuilt in memory each time the program starts. Neither mechanism was
verified; the fix does not depend on them, because exact search has no such behaviour.

## The mentor checks for Weeks 3 to 5, after hardening

Statuses are what the code and the generated outputs support. "Yours" means the part the brief says
only you can do.

| Week | Check | Status | Evidence |
|---|---|---|---|
| 3 | #1 correct answer from the documents | working | `docs/week4/failure-labels-dense.md`: 31 of the 32 cases pass on `gemini-3.5-flash-lite`; the one failure is a *retrieval* failure (`exact-security-email`), not a wrong answer |
| 3 | #2 shows the source | met | every answer lists the documents it cited (`generator.py`, `models.py`, `ask.py`) |
| 3 | #3 admits it doesn't know | met | the four refusal cases in `failure-labels-dense.md`; an empty index is now an error, not a fake refusal |
| 3 | #4 two chunk sizes | numbers produced, **observation yours** | `docs/week3/chunk-experiment.md`: both sizes found the right document for 9 of 9; 432 vs 894 chunks; scores and one rank moved |
| 4 | #1 which kind of failure, with evidence | tool run, **case write-up yours** | `docs/week4/failure-labels-dense.md` |
| 4 | #2 one change | met | `week4/CHANGES.md`: only hybrid search was added |
| 4 | #3 before/after number | produced | `docs/week4/eval-results.md`: hit-rate@3 27/28 for dense and 27/28 for hybrid (+0.0%); hit-rate@1 25/28 vs 24/28; MRR 0.923 vs 0.911 |
| 4 | #4 what the change did not fix | lists produced, **reading yours** | one case fixed, one regressed (`paraphrase-retirement`); five of the six exact-string predictions were wrong because dense search already finds them on this corpus |
| 5 | #1 to #4 fair sample, notes, names, ranking | tooling verified end to end, **work yours** | `tests/unit/test_week5_tools.py` runs sample, gate, carry-forward, grouping and ranking |

The Week 4 result is worth reading plainly: on this corpus, with exact dense search, the one change
did not raise hit-rate@3. That is a finding, not a defect, and it is yours to interpret.

## Test assets: what changed and why

The corpus changed after the Week 4 evaluation set was written, so cases that pointed at deleted
files would have been reported as retrieval failures no search could fix. They were replaced, before
anything was measured, with cases of the same kind on the current documents. The mapping is at the
top of `tests/eval_set.py`:

| old id | replaced by | kind (unchanged) |
|---|---|---|
| `exact-code-freeze` | `exact-policy-id` | exact string, favours keyword |
| `exact-collaboration-day` | `acronym-pim` | exact string, favours keyword |
| `negative-carryover-payout` | `negative-carryover-limit` | right document, negative statement |
| `detail-december-forfeit` | `detail-carryover-expiry` | right document, specific detail |
| `absent-parental-leave`, `absent-sick-days`, `absent-notice-period` | `detail-parental-leave`, `detail-sick-days`, `ambiguous-notice-period` | now answerable (the last one with two different answers) |

The set grew from 18 to 32 cases: it now covers the Acme policies, the Northstar remote-work policy,
the Nexora cloud policy, facts that exist only in the heavily repeated handbook, and four refusal
cases that really are absent. `tests/unit/test_eval_assets.py` checks that at least one accepted phrase of every case appears in an
expected document, that the cases whose phrases are bare numbers (which match almost anywhere) also
carry an `evidence` sentence still found in the documents, and every "absent" topic against the whole
corpus, so the set cannot go stale silently again. The six keyword-favouring and four dense-favouring cases that the Week 4 prediction
talks about still exist in those numbers.

## Errata added to earlier docs

Earlier week docs are not rewritten. Where a statement is no longer true, an erratum is added at the
top and the original text is kept: `week4/CHANGES.md`, `week4/findings.md` (whose empty case table was
regenerated with the current ids), `week5/CHANGES.md` and `week5/README.md`. `build-loop.md` and the
README were corrected directly because they describe the process and the setup, not a week's record.

## Not changed on purpose, and still open

- **The documents disagree** (18 vs 24 leave days, 30 vs 60 notice days, $1,000 vs INR 30,000
  learning budget). That is your decision about what the corpus is; the eval set accepts
  either answer where the question does not name a company.
- **Four fictional companies are mixed** and the four Northwind sample files are off-track for HR.
  Left in: they give Week 5 more to find.
- **The Excel workbook** was built for the earlier corpus and its Setup sheet predates the free
  provider. The risk rows in its CSV source (`tests/sheet-source/tc_risks.csv`) were updated to say what
  is now resolved, but `tests/Week3-Test-Cases.xlsx` itself is a binary built through Excel
  (`tests/sheet-source/build_xlsx.ps1`) and was not rebuilt.
- **The tags cannot run on the free setup.** They are the code as built; see the README.
- **The keyword index** is cached by chunk count only, so replacing a document with another that
  chunks to the same count, in a long-running server, would serve stale keyword results until a
  restart. `pipeline.ingest()` invalidates it, so the app's own path is safe.
- **Free-tier limits are per model, and they bite.** When measured, `gemini-flash-latest` (which resolved
  to `gemini-3.8-flash`) allowed 5 requests a minute and then hit a hard **daily** cap after about 18
  requests, which stopped a 32-question diagnosis halfway. `app/llm.py` detects that and stops with a
  clear message instead of retrying. The lite models answered 14 requests back to back with no limit
  reached, and the evidence in this repository was produced with the explicit name
  `gemini-3.5-flash-lite` (an alias such as `-latest` moves over time, so results cannot be replayed
  against it). Models also come and go: `gemini-2.5-flash` returned "no longer available". Limits change.

## How to verify

```powershell
.\.venv\Scripts\python.exe scripts\check_all.py
.\.venv\Scripts\python.exe scripts\compare_ann_exact.py
```
