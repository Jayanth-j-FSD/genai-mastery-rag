# Project docs

Read in this order:

1. **GOAL.md** — the goal, the delivery rules (branches, tags, review) and the status of every week. Start here.
2. **overview.md** — what we're building, why, and the week-by-week arc.
3. **project-info.md** — the folder structure and how a request actually flows through the files. Read this to *understand* the app.
4. **build-loop.md** — the nine-step process each week follows, and the two rules the project does not break.
5. **hardening/README.md** — what changed after the first three tags, and why.
6. **TODO.md** — the live checklist of everything to do.

## Per-week folders

Each week has its own folder and never edits an earlier one. `CHANGES.md` is the file to
open when someone asks "what did you actually do that week?".

- **week3/** — build the RAG app. `README.md` · `chunk-experiment.md` (generated numbers for check #4)
- **week4/** — debugging retrieval. `README.md` (the task) · `CHANGES.md` (what changed vs week 3) · `findings.md` (the deliverable: labels + numbers) · `eval-results.md` and `failure-labels-dense.md` (generated)
- **week5/** — error analysis. `README.md` · `CHANGES.md` · `worksheet.md` (your notes) · `coded-notes.md` (your group names) · `ranked-problems.md` (generated) · `taxonomy.md` (the deliverable)
- **hardening/** — what changed after the first three tags, and why
- **week6/ and later** — each later week adds its own folder (see GOAL.md)

## Which files a script may overwrite

Three kinds of file live in the week folders, and it matters which is which:

- **Written by hand** — `README.md`, `CHANGES.md`, `findings.md`, `taxonomy.md`. No script
  touches these.
- **Generated, then filled in by hand** — `worksheet.md`, `coded-notes.md`. A script creates
  the skeleton once; after that it holds your handwriting, so the generators refuse to
  overwrite them without `--force`.
- **Purely generated** — `eval-results.md`, `failure-labels-*.md`, `ranked-problems.md`. Safe
  to regenerate at any time, and never worth hand-editing. Each names at the top the command
  that produced it.
