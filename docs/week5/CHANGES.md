# Week 5 — what changed, and why

Week 5 is an analysis week, so it adds almost no application behaviour. It adds the tooling
that makes a *disciplined* analysis possible, and it reads what the app already logs. Nothing
from Week 3 or Week 4 was rewritten.

## New files

| File | What it does |
|------|--------------|
| `tests/trace_questions.txt` | A bank of about 40 questions used to build a population of real traces. Mixes clear questions, facts that live in two documents, questions absent from the corpus, and vague questions a real user would type. |
| `scripts/ask_batch.py` | Runs that bank through `pipeline.answer()` so every question is logged as a trace. Confirms before spending on API calls, and one failing question does not abandon the batch. |
| `scripts/sample_traces.py` | Draws a **seeded** random sample and writes `worksheet.md`, recording the population size, sample size, seed and the command that reproduces the identical draw. |
| `scripts/code_notes.py` | Validates that the notes pass is finished, then carries the failures into `coded-notes.md` with an empty `code:` per failure and the rules for naming a group. |
| `scripts/rank_problems.py` | Groups failures by name, ranks them by frequency multiplied by severity, and flags singleton groups and probable accidental name splits. |
| `app/worksheet.py` | Parses the hand-filled worksheet format, so the two scripts that read it do not each invent a parser. |
| `docs/week5/README.md` | The task, the four mentor checks, and the four steps. |
| `docs/week5/taxonomy.md` | The hand-written deliverable: group definitions, ranking, chosen target, prediction. |

## Changed files

| File | Change |
|------|--------|
| `docs/README.md`, `docs/TODO.md`, `docs/project-info.md`, `README.md` | Week 5 files and commands listed. |

No file under `app/rag/` was touched. Week 5 changed no answer behaviour at all, which is the
correct outcome for an analysis week: if the app behaved differently this week, the twenty
traces would not describe the app that Week 4 was measured on.

## The gap this week uncovered

Week 4's `diagnose.classify()` calls the retriever and the generator **directly**, not through
`pipeline.answer()`. That is right for a diagnosis tool, since it needs to force a retrieval
mode and grade the result, but it means those runs write **no traces**. So after a full Week 4
evaluation the trace log could still be almost empty, and Week 5's deliverable is "read about
20 real traces".

Rather than make the diagnosis tool log traces — which would mix synthetic evaluation runs
into the log that is supposed to represent real usage — Week 5 adds `ask_batch.py`, which goes
through the ordinary answer path. The population is therefore made of genuine request traces,
indistinguishable from a user's.

## Why the process is enforced in code

The brief is specific that the honest note comes **before** any grouping, and the mentor checks
for it. That ordering is easy to agree with and easy to skip, because it feels faster to sort
into categories you already suspect. Three design choices defend it:

1. `worksheet.md` offers **no** list of categories. There is nothing to sort into, so the only
   thing you can write is what you saw.
2. `code_notes.py` **refuses to run** until every trace has a verdict and every failure has a
   note and a severity. Grouping is physically unavailable until the reading is done.
3. The codes live in a **separate file**, generated from the finished notes. Adding a group
   name cannot quietly precede writing the note it is based on.

`sample_traces.py` and `code_notes.py` also refuse to overwrite their output without `--force`,
because both files end up holding handwriting that no script can regenerate.

## Requirement to code, check by check

| Mentor check | Satisfied by | How to demonstrate it |
|---|---|---|
| #1 A fair sample, not the good examples | `scripts/sample_traces.py` uses `random.Random(seed).sample()` and writes the seed, population size and reproduction command into the worksheet header | Show the worksheet header, then re-run the printed command and show the identical draw |
| #2 An honest note per failure, written before grouping | The worksheet's `note:` fields, plus `app/worksheet.py` → `validate_notes()` enforcing them via `scripts/code_notes.py` | Run `code_notes.py` against an unfinished worksheet and show that it refuses |
| #3 Clear group names a stranger would understand | `coded-notes.md` ships the naming rules and worked examples; `rank_problems.py` → `_near_duplicates()` catches accidental splits | Read the group names in `taxonomy.md` section 2 aloud to someone who has not seen the corpus |
| #4 Ranked, with a chosen target | `scripts/rank_problems.py` → `_group()` and the impact sort; the choice and prediction in `taxonomy.md` sections 3 and 4 | Show `ranked-problems.md` and the written prediction |

## The review pass — what it caught

| Found | Why it mattered |
|---|---|
| `classify()` logs no traces | Week 5 would have had nothing to sample. Fixed by adding `ask_batch.py` on the traced path rather than by polluting the log with evaluation runs. |
| A question bank of exactly 20 | Sampling 20 from 20 is a census, not a sample, and the fairness argument collapses. The bank is about 40, and `sample_traces.py` says so explicitly when the population is too small. |
| Regenerating the worksheet would delete handwritten notes | Both generators now refuse to overwrite without `--force`. |
| Codes differing only in spacing would split a real problem | `normalize_code()` treats "Wrong Document", "wrong document" and "wrong-document" as one group, and near-duplicate names are flagged for review. |
| A worksheet with zero failures marked | Would produce an empty taxonomy with no explanation. `code_notes.py` now stops and explains what counts as a failure, including refusals on answerable questions. |
| Severity given as free text | `normalize_severity()` accepts only 1, 2 or 3 and reports the offending trace, so the impact arithmetic cannot silently skip a failure. |
| A multi-line answer would be truncated | The worksheet writes `**Answer:** ...` on one line and the parser reads one line per field, so a model answer containing a bullet list would have lost everything after its first newline when carried into the coded notes. Questions and answers are now flattened onto one line first. |
| `input()` crashed on piped stdin | The batch runner's confirmation prompt raised `EOFError` with no terminal attached. It now says to re-run with `--yes` rather than guessing a yes and spending money. |
| The worksheet had no machine-readable provenance | Seed, population and sample size were in prose only. They are now also `<!-- key: value -->` comments, so later steps report the same numbers without anyone retyping them. |
| Prose bullets could have been read as data fields | The worksheet's instructions contain lines like `- **verdict** — ...`. Verified these cannot match the field parser (the `**` prevents it) and that anything before the first `## trace` block is ignored outright. |

## Status, stated honestly

The tooling is written and reviewed but **has not been executed** — this machine has no Python
and no API key. More importantly, the deliverable itself is deliberately unfinished: the twenty
notes, the group names and the prediction are Jayanth's to write after a real run, because that
is the part the brief says cannot be automated. `taxonomy.md` therefore ships as a template with
empty fields, not as a filled-in report.

`git checkout week-4` still runs the app exactly as Week 4 left it.
