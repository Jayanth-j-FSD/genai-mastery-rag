# Week 5 — Error Analysis

> **Note (2026-10-11).** Step 2 below: the "exact command that reproduces the identical draw" now
> writes to a separate file and takes `--upto N`, so re-checking a sample can never overwrite
> your notes. Details in [../hardening/README.md](../hardening/README.md).

## The task (from the brief)
Until now you fixed whatever problems you happened to notice, which misses the ones you never
saw. This week you become systematic: read a fair batch of about 20 real answers the app gave,
write one honest sentence about what went wrong in each failure, group those notes into a few
clearly-named problems, rank them by how often they happen and how much they hurt, and pick
the one to attack next — writing your prediction down first.

Almost no new application code. Week 5 reads what the app already logs.

## Definition of done — the 4 mentor checks
1. **Did you read a fair sample, not just the good examples?**
2. **Is there an honest note per failure, written before grouping them?**
3. **Do the problem groups have clear names a stranger would understand?**
4. **Are the problems ranked, with a chosen target to fix next?**

## The one part that cannot be automated
The brief says it directly: reading your own failures is the one part that can't be automated.
It is where you find the problems you never guessed were there.

So the scripts here do the mechanical work only — building a population of traces, drawing a
fair sample, carrying your notes forward, counting and ranking. **The verdict, the note and
the severity on each trace are yours to write.** `code_notes.py` refuses to run until they
exist, which is what stops the process collapsing into "sort into the categories I already
had in mind".

## The four steps

### Step 1 — build a population of real answers
```bash
python scripts/ask_batch.py
```
Runs `tests/trace_questions.txt` (about 40 questions) through the normal answer path, so each
one is logged as a trace. The bank mixes clear questions, questions whose answer sits in two
documents, questions that are not in the corpus at all, and vague questions a real user would
type. The vague ones produce the most interesting failures.

Why more than 20: **sampling 20 out of 20 is not sampling.** A larger population is what makes
the random draw mean something, which is the first thing the mentor checks.

Costs one embedding call and one small answer call per question, so it asks for confirmation
before it starts.

### Step 2 — draw a fair sample
```bash
python scripts/sample_traces.py --n 20
```
Takes a **seeded** random sample and writes `worksheet.md`. The worksheet records the
population size, the sample size, the seed, and the exact command that reproduces the
identical draw — which is how you demonstrate the sample was not curated.

It will not overwrite an existing worksheet without `--force`, because that file will contain
notes you wrote by hand.

### Step 3 — read every trace and write an honest note
Open `worksheet.md` and fill in three fields per trace, by hand:

- **verdict** — `ok` or `bad`. A refusal on a question the documents *do* answer is `bad`.
  So is a confident answer to something the documents never mention. So is a technically-true
  answer that misses the specific number that was asked for.
- **note** — for every `bad`, one honest sentence on what actually went wrong. In your own
  words. Not a category, not a fix, just what you saw.
- **severity** — `1` mildly wrong, `2` misleading, `3` confidently wrong in a way someone
  could act on and be harmed by.

Read all twenty, including the ones that look fine. Then, and only then:

```bash
python scripts/code_notes.py
```
This checks every trace has a verdict and every failure has a note and severity, and refuses
to continue otherwise. When it passes, it writes `coded-notes.md` containing only the failures
with your notes carried over, plus an empty `code:` per failure and the rules for naming a
group well. Add one group name per failure there.

### Step 4 — rank them and choose a target
```bash
python scripts/rank_problems.py --save
```
Groups the failures by name and ranks them by **impact = how often it happened multiplied by
how much it hurt** (the sum of its severities). It also flags two things worth knowing: groups
that occurred only once (not yet a pattern) and pairs of names that look like the same problem
split in two (a split problem looks rarer than it is and can lose its place in the ranking).

The output is written to `ranked-problems.md`. Then write up `taxonomy.md` by hand: the group
definitions, the ranking, your chosen target, and your prediction.

## Why a public benchmark would not have told you any of this
The brief raises benchmarks (MMLU, HumanEval) alongside this work, and the contrast is the
point. Those score a model on general knowledge and general coding against questions it has
never seen. They say nothing about whether *your* app finds *your* documents and grounds its
answers in them. A model can top a public leaderboard and still cite the wrong policy file for
your users, because that failure lives in your retrieval and your prompt, not in the model's
general ability. The twenty traces you read this week are the only evaluation that is actually
about your app.

## Files in this folder

| File | Owner | What it is |
|---|---|---|
| `README.md` | written | this file: the task and the four steps |
| `CHANGES.md` | written | what changed vs Week 4 |
| `worksheet.md` | generated, then **yours** | the sampled traces and your notes |
| `coded-notes.md` | generated, then **yours** | the failures with your group names |
| `ranked-problems.md` | generated | the ranking; regenerate freely, never hand-edit |
| `taxonomy.md` | **yours** | the deliverable: named groups, ranking, target, prediction |
