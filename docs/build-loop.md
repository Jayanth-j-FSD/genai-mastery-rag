# The Build Loop — how each week is added to this app

One app, carried forward week by week. Nothing is duplicated and nothing from an earlier
week is overwritten: each week adds code, adds its own `docs/weekN/` folder, and is frozen
as a git tag so any week can be shown in isolation.

```
git tag week-3   ← the app as the Week 3 mentor sees it
git tag week-4   ← Week 3 + this week's one change
git tag week-5   ← Week 4 + this week's analysis
```

To show any past week exactly as it was: `git checkout week-3`, look around, then
`git checkout main` to come back.

---

## The loop, in order

Every week runs these nine steps in this order. Steps 6 to 8 are the part that matters:
the code gets checked against the *brief*, not against itself.

| # | Step | Output |
|---|------|--------|
| 1 | **Read the brief. Restate the requirement in one paragraph.** | the requirement, in plain words, in `docs/weekN/README.md` |
| 2 | **Name the definition of done** — the mentor's own check questions, copied verbatim | a checklist in `docs/weekN/README.md` |
| 3 | **Build** only what steps 1-2 name. Nothing extra. | new/changed files under `app/`, `scripts/`, `tests/` |
| 4 | **Comment for a beginner** — one line per non-obvious decision | comments in the code itself |
| 5 | **Write the week's docs** — a new `docs/weekN/` folder, never editing a previous week's | `README.md`, `CHANGES.md`, `findings.md` |
| 6 | **Bug pass** — read every changed file line by line, hunting edge cases | fixes, or a note that none were found |
| 7 | **Clean pass** — dead code, stale comments, unused settings, wrong docs | a tidy diff |
| 8 | **Requirement-vs-code pass** — re-read the brief and prove each check is met by pointing at a file and line. Anything unproven is a gap, and gaps get fixed, then step 6 runs again. | a table in `docs/weekN/CHANGES.md` mapping check → code |
| 9 | **Commit and tag** | `git commit` + `git tag week-N` |

Step 8 is the one that catches drift. It is deliberately done *after* the code is written,
by re-reading the brief cold rather than trusting memory of it.

---

## Two rules this project does not break

**One change per week, when the brief says one change.** Week 4's brief is explicit: *"make
one improvement"*, and the mentor checks *"did they make one change (not five)?"*. Shipping
four improvements would make the before/after number meaningless, because you could not say
which one earned it. Other techniques from the topic list get studied and written down as
*considered and deferred*, with the reason. That is a stronger answer than implementing them.

**Never rewrite a documented meaning.** If a function's docstring says what it returns,
later weeks add a new function beside it rather than changing what the old one does. Week 3's
`retrieve()` still behaves exactly as its docstring says, in every later week. This is what
keeps `git checkout week-3` honest.

---

## What cannot be faked

This machine has no Python and no API key, so **no week's numbers can be produced by writing
them into a document**. Every script below prints its own numbers when you run it, and every
docs table that needs a real measurement ships with an empty cell and the command that fills
it. An empty cell is honest. A guessed number would not survive the mentor asking
"show me".

Week 5 is stricter still: its deliverable is ~20 traces *you* read. The brief says reading
your own failures is "the one part that can't be automated". So Week 5 builds the sampling,
worksheet and ranking tools, and the honest note on each failure stays yours to write.

---

## Week 4 — Debugging Retrieval

**The requirement.** The app works but is sometimes wrong, and "sometimes wrong" cannot be
fixed. Separate the two kinds of wrong: it fetched the *wrong document*, or it fetched the
*right document and still answered badly*. Those need opposite fixes. Then make **one**
improvement, and prove it with a before-and-after number.

**Definition of done — the mentor's four questions.**
1. For a specific failure, can you show which of the two kinds it is, with evidence?
2. Did you make one change, not five?
3. Is there a before-and-after number, not "it feels better"?
4. Did you notice which failures your change did *not* fix?

**The plan.**

| Piece | File | Serves |
|-------|------|--------|
| A labelled question set, including questions built to fail | `tests/eval_set.py` | 1, 3 |
| Failure classifier: retrieval failure vs generation failure, with the evidence attached | `app/rag/diagnose.py` | 1 |
| Inspection view — question / what was fetched / final answer, side by side | `scripts/inspect.py`, `/inspect` endpoint | 1 |
| Keyword search (BM25), so exact terms like `ERR-4032` stop being missed | `app/rag/keyword.py` | 2 |
| Rank fusion (RRF) joining keyword + meaning results | `app/rag/fusion.py` | 2 |
| The switch: `dense` reproduces Week 3 exactly, `hybrid` is the change | `app/config.py`, `app/rag/retriever.py` | 2, 3 |
| Metrics: hit-rate@3, recall@k, MRR, run over both modes with the delta | `scripts/eval_retrieval.py` | 3, 4 |
| The report: labels with evidence, the number, and what stayed broken | `docs/week4/findings.md` | 1, 3, 4 |

**The one change is hybrid retrieval** (BM25 keyword search fused with the existing dense
search via RRF). Chosen because the failure it targets is the *retrieval* kind, which is the
kind a smarter answer-model cannot fix, and because it needs no new API key and no new model
download. Reranking, query rewriting, HyDE and MMR are deliberately **not** built this week;
`docs/week4/CHANGES.md` records why.

---

## Week 5 — Error Analysis

**The requirement.** Stop fixing whatever you happen to notice. Read a fair sample of about
20 real answers, write one honest sentence per failure *before* deciding on any categories,
group those notes into a few clearly-named problems, rank them by how often and how badly
they hurt, and pick the one to attack next, writing your prediction down first.

**Definition of done — the mentor's four questions.**
1. Did you read a fair sample, not just the good examples?
2. Is there an honest note per failure, written before grouping them?
3. Do the problem groups have clear names a stranger would understand?
4. Are the problems ranked, with a chosen target to fix next?

**The plan.**

| Piece | File | Serves |
|-------|------|--------|
| Seeded random sample of N traces (fair, reproducible, not cherry-picked) | `scripts/sample_traces.py` | 1 |
| A worksheet with one row per sampled trace and an empty note field, deliberately offering **no** categories | `docs/week5/worksheet.md` | 2 |
| Your notes, then your codes, kept in one file | `docs/week5/coded-notes.md` | 2, 3 |
| Ranker: counts each named group, multiplies frequency by severity, orders them | `scripts/rank_problems.py` | 3, 4 |
| The ranked taxonomy, the chosen target, and the prediction written before the fix | `docs/week5/taxonomy.md` | 3, 4 |

Week 5 adds almost no application code, by design. It reads what the app already logs.
The sampling is seeded so the mentor can re-draw the identical sample and confirm it was
not curated.

---

## Where each week's files live

```
docs/
├── build-loop.md      ← this file: the process
├── overview.md        ← what the app is, and the week-by-week arc
├── project-info.md    ← the structure and how a request flows
├── TODO.md            ← the live checklist
├── week3/             ← frozen: the build week
├── week4/             ← README (task) · CHANGES (what changed vs week 3) · findings (the numbers)
├── week5/             ← README · CHANGES · worksheet · coded-notes · taxonomy
└── week6/             ← not started
```

Each `weekN/CHANGES.md` is the file to open when someone asks "what did you actually do that
week?". It lists the changed files and maps every mentor check to the code that satisfies it.
