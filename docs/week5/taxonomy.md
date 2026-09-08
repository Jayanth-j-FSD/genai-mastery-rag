# Week 5 — the error taxonomy (the deliverable)

This is the file the mentor reads. It is written by hand, on purpose: the numbers come from
`ranked-problems.md`, but the naming, the judgement and the prediction are the actual work.

Fill it in after completing the four steps in `README.md`.

---

## 1. How the sample was drawn (check #1)

Copy these from the header of `worksheet.md`, which records them automatically.

- Traces available in the log when drawn:
- Sample size:
- Random seed:
- Command that reproduces the identical sample:

One sentence on why this is a fair sample rather than a curated one:

>

---

## 2. The problem groups (check #3)

One row per group. The name has to stand on its own — someone who has never seen the corpus
should understand what went wrong from the name alone. Describe what you **observed**, not
what you think caused it.

| Group name | What it means, in one sentence | Example trace |
|---|---|---|
| | | |
| | | |
| | | |
| | | |

Guard against the two failure modes here: one group per failure means nothing was grouped,
and two groups for twenty failures is too coarse to act on. Three to six is the useful range.

---

## 3. The ranking (check #4)

From `python scripts/rank_problems.py --save`. Impact is how often it happened multiplied by
how much it hurt, which is the sum of the group's severities.

| # | Group | Occurrences | Mean severity | Impact | % of traces read |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
| 4 | | | | | |

Notes on anything the script flagged:

- Groups that occurred only once, and whether you kept them separate or merged them:
- Any pair of names that looked like the same problem split in two:

---

## 4. The chosen target, and the prediction (check #4)

The highest-impact group is not automatically the right target. A rare but harmful problem can
outrank a frequent cosmetic one, and a cheap fix for the second-place problem can beat an
expensive fix for the first. Say which you picked and why.

**Target chosen:**

>

**Why this one and not the top-ranked group** (skip if they are the same):

>

**The prediction, written before changing anything.** Be specific enough to be wrong:

> If I change ________, I expect ________ to go from ______ to ______, and I expect it to have
> no effect on ________.

**How I will know if I was wrong:**

>

---

## 5. What I did not expect

The point of reading a fair sample is finding problems you would never have guessed. If
nothing here surprised you, the sample was probably too small or the reading too generous.

>

---

## 6. What this says about last week's change

Week 4 changed retrieval and measured hit-rate@3. Now that twenty real answers have been read,
does that number look like it captured the app's actual problems, or did it measure the one
thing that happened to be easy to measure?

>
