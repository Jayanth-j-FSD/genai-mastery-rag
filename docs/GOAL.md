# Goal and delivery plan

## The goal

Finish the course build weeks as one app, one week at a time, up to the last week whose brief has
been released. Each week lives on its own branch with its own tag, so a reviewer can read one week
in isolation. Nothing from an earlier week may break, and everything ends up on GitHub.

Track: C (HR policy). Stack: Python 3.12, FastAPI, Chroma, a local ONNX embedding model, Gemini
through the OpenAI-compatible endpoint (free tier, no paid APIs).

## What "done" means for every week

A week is done only when all of these hold. They are the gate before its tag is created.

1. The brief is read, the requirement is restated in one paragraph, and the mentor's check questions
   are copied verbatim into `docs/weekN/README.md`.
2. The code builds only what the brief asks. Alternatives that were studied are written down as
   deferred, with the reason, in `docs/weekN/CHANGES.md`.
3. `python scripts/check_all.py` is green: compile check, import of every module, and the offline
   unit tests (stub model and temporary index, so no network and no quota).
4. `docs/weekN/CHANGES.md` has a table that maps each mentor check to the file and line that
   satisfies it. Anything unproven is listed as a gap, not hidden.
5. A review (by someone who did not write the code) has run, and every real finding is
   fixed or rejected with a reason.
6. Every number in the docs was printed by a script. A measurement that has not been run is an empty
   cell next to the command that fills it.
7. Parts that are your own work (reading traces, grading answers, the ship decision) are
   left as clearly marked blanks. Tooling is built, the judgement is not written for you.

## Delivery rules (branches, tags, review)

- **One branch per week**, started from the tip of the previous week:
  `week-5-hardening`, `week-6-evals`, `week-7-agent-loops`, `week-8-agent-failure-modes`, `week-9-mcp`.
- **One annotated tag per week**, `week-N`, on the branch tip once the gate above passes. The existing
  tags `week-3`, `week-4` and `week-5` never move. The hardening branch is tagged `week-5-hardened`.
- **Small commits**, one logical piece each, written as a plain sentence starting with the week
  (`Week 6: add the assertion checks`). Tests land with the code they test.
- **One pull request per week**, opened against the previous week's branch so it shows only that
  week's change. Merge in order with merge commits (no squash) so every tag stays reachable from `main`.
- **No force-push** of a branch a reviewer has seen. Fixes go in as new commits.
- **Secrets** never enter a commit: keys live in the ignored `.env` only.
- **Documented meanings never change.** A later week adds a new function beside the old one. Week 3's
  `retrieve()` still means what its docstring says.

## The plan

| Week | Brief in one line | What gets built | Needs you |
|---|---|---|---|
| 3 to 5 | RAG app, debugging retrieval, error analysis | Built and tagged. Hardened on `week-5-hardening` (see below) | Read about 20 traces and write the notes (Week 5 is theirs) |
| 6 | Evals: one-command test set, validated judge, before/after per problem type | Eval cases, assertion checks, LLM judge, judge-validation tooling, regression cases from Week 5 failures, one measured improvement | Grade about 20 answers by hand so the judge can be validated |
| 7 | Agent loop by hand, with a fixed workflow to race it against | Tool-calling loop with visible steps and stop limits, HR tasks, fixed workflow, race on speed, cost and reliability | The ship decision |
| 8 | Agent failure modes, trajectory evals, prompt injection | Path-level scoring, failure labels, an injection test and a defence, one measured fix | Naming what could still get through |
| 9 | MCP: discover tools, build a server | An MCP client that discovers tools, an HRIS server and a policy-search server, a raw-message demo | Explaining where the AI runs |
| 10, 11 | Not released yet | Same process once the briefs exist | The briefs |

### Week 5 hardening (before any later week)

The three tagged weeks were built before the app was first run. Running it found problems that would
make a reviewer's first run fail, so they are fixed on their own branch with their own docs
(`docs/hardening/`):

- Free-provider support (Gemini answers, local embeddings) so the app runs without paid keys.
- Dense search made exact. Chroma's approximate index returned the wrong top result for many
  questions on this corpus, and differently on each run. `scripts/compare_ann_exact.py` measures it.
- Chat calls throttled and retried (`app/llm.py`) so the free tier's per-minute limit does not break runs.
- Stale test assets rewritten for the current documents, and the answer key moved out of the corpus.
- Dependencies pinned and the README refreshed.
- A regression gate (`scripts/check_all.py`) so "nothing is broken" is a command, not a promise.

## Dependencies and honest limits

- Weeks 10 and 11 cannot be built until their briefs exist. Building to a guess would break the rule
  of doing exactly what was asked.
- Week 6 asks for last week's real failures as tests. Those come from your own Week 5
  notes. Until they exist, the converter is tested against a fixture and the regression set is empty.
- The free Gemini tier limits requests per minute **and per day, per model**. The flagship alias hit a
  hard daily cap after about 18 requests during Week 5 hardening, so heavy runs use the lite models,
  which answered 14 requests back to back. Live runs are throttled and stop with a clear message when a daily
  quota is gone. From Week 6, model calls are also cached by their exact input. Results are only ever
  reported from a run that happened, and the model that produced them is named next to them.

## Status

Updated as the work lands. `done` means the gate above passed.

| Item | Status |
|---|---|
| Week 5 hardening | done: gate green (196 offline tests); live-run outputs in `docs/week3/`, `docs/week4/` and `docs/hardening/`; tag `week-5-hardened` |
| Week 6 | done: gate green (345 offline tests, also on a clean export without `.env`); 41-case eval set, rule checks, binary judge, cached runner; three improvement experiments, the only gain is hybrid search with 6 chunks (38 to 39 of 41); tag `week-6`. Left for you: grade the judge sheet, review the references, add the Week 5 failures, write the interpretation |
| Week 7 | done: gate green (482 offline tests, also on a clean export without `.env`); agent loop built by hand, memory, three tools, a fixed workflow, nine HR tasks, and a race on 27 runs per approach that is reported both as raced (agent 26 of 27, workflow 27 of 27) and re-scored under the corrected checks (25 and 24); tag `week-7`. Left for you: which approach to ship, and why (`docs/week7/findings.md`, section 5) |
| Week 8 | done: gate green (729 offline tests, also on a clean export without `.env`); a grader of the path an agent takes (eight failure modes), three defence layers, a 15-attack injection suite and a per-tool call budget whose prediction was written before it was measured; measured on 33 runs in each of two arms and a noise run: the four judged predictions held (`over-calling` 7 runs to 0, right answers 29 to 31, mean tokens per run 4,861 to 4,392 against a noise floor of 4.8%), the control on a model that never reaches the cap is identical, the defences refused and withheld nothing in 33 live runs, and 8 of 15 attacks worked with the defences off against 2 of 15 with them on; tag `week-8`. Left for you: what could still get through (`docs/week8/findings.md`, section 4) |
| Week 9 | not started |
| Weeks 10, 11 | waiting for briefs |
