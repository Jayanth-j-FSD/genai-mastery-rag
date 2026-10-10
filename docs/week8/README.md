# Week 8: Agent failure modes, trajectory evals, and prompt injection

## The task (from the brief)

*Look at a batch of your agent's runs and find where it took a wrong path even when the answer looked
right. Try a simple attack that hides an instruction in a document, then defend against it, and fix your
top failure, measuring the improvement.* The track line for HR policy: *find the outcome-versus-trajectory
gap in the HR agent, then close one failure mode.*

In plain words: a right answer can come from a wrong path (a date worked out in the model's head instead of
the date tool), and a path that works today by luck breaks on tomorrow's input. So this week scores the
PATH as well as the answer. It also tests whether text the agent reads (a document it retrieves) can take
over the agent, and builds defences that are measured, not assumed.

## Definition of done: the mentor's four questions

1. Did you find a case where the answer was right but the path was wrong?
2. Did you successfully trick your own agent, then stop the trick?
3. Is there a before-and-after number on your top failure?
4. Can you name what could still get through?

## What was built, and which check it serves

| Piece | File | Serves |
|---|---|---|
| Trajectory grading: eight failure modes as plain rules, expected tool sequences, tool-choice accuracy, the outcome-versus-trajectory gap, cost per run (mean, p95, p99) | `evals/trajectory.py` | 1 |
| Run the agent on the Week 7 tasks and grade every path; or re-grade a saved race for free | `scripts/run_trajectories.py` | 1 |
| An injection suite: 13 attacks (10 indirect, planted in poisoned documents in a private throwaway index; 3 direct), each with a canary so success is detected mechanically | `evals/injection.py`, `scripts/run_injection.py` | 2 |
| Three defence layers, each switchable and measurable alone: sanitize what it reads, guard what it does, validate what it says | `app/agent/defense.py`, wired into `app/agent/loop.py` | 2 |
| The before-and-after number on the top failure mode | `scripts/compare_trajectories.py`, `docs/week8/CHANGES.md` | 3 |
| What still gets through: written as executable statements in a test, measured, and mapped to the OWASP list in `owasp-map.md` | `tests/unit/test_injection.py` (`WhatEachLayerStopsTests`), `docs/week8/findings.md` | 4 |

## Run it

```powershell
.\.venv\Scripts\python.exe scripts\run_trajectories.py --label before             # model calls: runs the agent, grades every path
.\.venv\Scripts\python.exe scripts\run_trajectories.py --grade race-race --label regraded   # free: re-grade a saved Week 7 race
.\.venv\Scripts\python.exe scripts\run_injection.py --static                      # free: what the sanitizer alone removes
.\.venv\Scripts\python.exe scripts\run_injection.py --label final                 # model calls: every attack, defences off and on
.\.venv\Scripts\python.exe scripts\compare_trajectories.py before after --save
```

## The failure modes (each is a rule a reviewer can disagree with)

`loop`, `over-calling`, `wrong-tool`, `skipped-tool`, `made-up-input`, `unverified-citation`,
`gave-up-quietly` and `no-answer`, plus `blocked-answer` for a legitimate answer the defences withheld. The
definitions are in the docstring of `evals/trajectory.py` and every one works from the steps a run recorded,
with no model judging it. The gap is the number of runs whose outcome passed while the path showed at least
one mode. The grader was validated against real runs before it was trusted: see `CHANGES.md`.

## The three defence layers

1. **Sanitize what it reads.** Every tool result is labelled as untrusted data; hidden text (HTML comments,
   zero-width characters) is dropped; sentences that address an AI are cut out. Pattern matching: it
   catches the common phrasings and a rephrased attack gets past it. On the real corpus it removes nothing.
2. **Guard what it does.** Tools are read-only, and arguments are checked before a call runs: a date must
   come from the question or an earlier result, numbers must be in a sane range, and a note to memory may
   not be an instruction. This is least privilege.
3. **Validate what it says.** The final answer must cite a document the agent really retrieved (or be the
   plain "I don't know"), may contain only email and web addresses that appear in the approved documents,
   and may not repeat the system prompt.

All three are off unless the caller passes `run_agent(..., defense=Defense(...))`, so Weeks 3 to 7 behave
exactly as before.

## The part that is yours

Check 4 asks what could still get through. `findings.md` holds the measured numbers and the list of attacks
that got past every layer, but the answer in your own words, and the judgement about how much each gap
matters, are blank for you to write.
