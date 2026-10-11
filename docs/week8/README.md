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
| An injection suite: 15 attacks (12 indirect, planted in poisoned documents in a private throwaway index; 3 direct), each with a canary so success is detected mechanically | `evals/injection.py`, `scripts/run_injection.py` | 2 |
| Three defence layers, each switchable and measurable alone: sanitize what it reads, guard what it does, validate what it says | `app/agent/defense.py`, wired into `app/agent/loop.py` | 2 |
| The before-and-after number on the top failure mode, and the prediction written before it was measured, checked as arithmetic | `scripts/compare_trajectories.py`, `scripts/check_prediction.py`, `docs/week8/CHANGES.md` | 3 |
| A one-run illustration of the call budget on the unanswerable question: eight searches and no answer, then three searches and a refusal | `docs/week8/example-budget.md` | 3 |
| What the tests and the OWASP map record about what gets through: inputs for check 4, whose answer is yours to write in your own words (`findings.md`, section 4) | `tests/unit/test_injection.py` (`WhatEachLayerStopsTests`), `docs/week8/findings.md` | 4 |

## Run it

```powershell
.\.venv\Scripts\python.exe scripts\run_trajectories.py --label before             # model calls: runs the agent, grades every path
.\.venv\Scripts\python.exe scripts\run_trajectories.py --grade race-race --label race-regraded   # free: re-grade a saved Week 7 race
.\.venv\Scripts\python.exe scripts\run_injection.py --static                      # free: what the sanitizer alone removes
.\.venv\Scripts\python.exe scripts\run_injection.py --label r2-final              # model calls: every attack, defences off and on
.\.venv\Scripts\python.exe scripts\compare_trajectories.py before after --save
.\.venv\Scripts\python.exe scripts\run_trajectories.py --show before               # free: print a saved run's report
.\.venv\Scripts\python.exe scripts\run_injection.py --compare layer-sanitize layer-guard-fixed layer-validate final   # free
.\.venv\Scripts\python.exe scripts\check_prediction.py before-final after-final --noise before-final-2   # free: the prediction, read against the noise floor
.\.venv\Scripts\python.exe scripts\run_trajectories.py --regrade before            # free: grade a saved run again with today's rules, in place
.\.venv\Scripts\python.exe scripts\run_trajectories.py --interleave before-final after-final:agent_max_calls_per_tool=3 before-final-2 --repeats 3   # model calls: the measured pair and its noise run, side by side
.\.venv\Scripts\python.exe scripts\run_injection.py --show final --rescore         # free: a saved run judged by today's detectors
.\.venv\Scripts\python.exe scripts\replay_defense.py before before-p control race-race   # free: what the defences would do to saved legitimate runs
```

A saved run is never overwritten by accident: a label that already exists is refused unless `--force` is given, for trajectory
runs and for injection runs.
A comparison reads only the (task, repeat) pairs both runs completed, so a run cut short by a daily quota is still
compared like with like. The per-tool call budget is switched on for one run with `--set agent_max_calls_per_tool=3`.

## The failure modes (each is a rule a reviewer can disagree with)

`loop`, `over-calling`, `wrong-tool`, `skipped-tool`, `made-up-input`, `unverified-citation`,
`gave-up-quietly` and `no-answer`, plus `blocked-answer` for an answer the defences withheld. The
definitions are in the docstring of `evals/trajectory.py` and every one works from the steps a run recorded,
with no model judging it. The gap is the number of runs whose outcome passed while the path showed at least
one mode. The grader was validated against real runs before it was trusted: see `CHANGES.md`.

## The three defence layers

1. **Sanitize what it reads.** Every tool result is labelled as untrusted data; hidden text (HTML comments,
   zero-width characters) is dropped; sentences that address an AI are cut out; a document's name is checked too, and
   a result cannot close the data label early. Pattern matching: it catches the common phrasings, a rephrased attack
   gets past it, and an innocent sentence that looks like an instruction would be cut. On the real corpus it removes
   nothing.
2. **Guard what it does.** Tools are read-only, and arguments are checked before a call runs: a date must
   be one the question states (in any common written form) or one a date or calculator tool produced, so a poisoned
   document cannot supply the date it wants used; numbers must be in a sane range (plain, underscore and exponent forms); and a note to
   memory may not be an instruction or an address. This is least privilege.
3. **Validate what it says.** The final answer must cite a document the agent really retrieved (a short
   "I don't know" needs no citation), may contain only email addresses and `http`, `https`, `ftp`, `hxxp` and `www` addresses that appear in the approved documents,
   and may not repeat 60 or more characters in a row of the system prompt.

All three are off unless the caller passes `run_agent(..., defense=Defense(...))`, so Weeks 3 to 7 behave
exactly as before.

## The part that is yours

Check 4 asks what could still get through. `findings.md` holds the measured numbers and the list of attacks
that got past every layer, but the answer in your own words, and the judgement about how much each gap
matters, are blank for you to write.
