# Project docs

Read in this order:

1. **overview.md** — what we're building, why, and the whole Week 3-6 arc. Start here.
2. **project-info.md** — the folder structure and how a request actually flows through the files. Read this to *understand* the app.
3. **build-loop.md** — the nine-step process each week follows, and the two rules the project does not break.
4. **week5/README.md** — the current week's task and definition of done.
5. **TODO.md** — the live checklist of everything to do.

## Per-week folders

Each week has its own folder and never edits an earlier one. `CHANGES.md` is the file to
open when someone asks "what did you actually do that week?".

- **week3/** — build the RAG app. `README.md`
- **week4/** — debugging retrieval. `README.md` (the task) · `CHANGES.md` (what changed vs week 3) · `findings.md` (the deliverable: labels + numbers)
- **week5/** — error analysis. `README.md` · `CHANGES.md` · `worksheet.md` (your notes) · `coded-notes.md` (your group names) · `ranked-problems.md` (generated) · `taxonomy.md` (the deliverable)
- **week6/** — evals (placeholder)

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
