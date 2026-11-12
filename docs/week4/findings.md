# Week 4 — findings (the deliverable)

> **Erratum (2026-10-11).** Written before anything was run, and kept as written. Since then the
> corpus changed, so `tests/eval_set.py` was rewritten before any measurement: the six exact-string
> and four paraphrase cases of section 1 still exist, with `exact-code-freeze` and
> `exact-collaboration-day` replaced by `exact-policy-id` and `acronym-pim` (same kind), and the
> case table in section 3 below has been regenerated with the current ids (its cells are still empty). The mapping is at
> the top of `tests/eval_set.py` and in [../hardening/README.md](../hardening/README.md). The code
> **has** now been run: the generated output is in `eval-results.md` and `failure-labels-dense.md`
> beside this file. Section 2's corpus-question count is updated to 28. The prediction, the interpretation
> and the contents of sections 2 to 6 are still yours to write.

This is the file the mentor reads. The prediction section is filled in already, because a
prediction is only worth anything if it is written **before** the measurement. Every table
that needs a real number is deliberately empty, with the command that fills it, because the
code has not been run yet on this machine (no Python, no API key).

## Fill this file in three commands

```bash
python scripts/ingest.py                                   # build the index
python scripts/diagnose_failures.py --mode dense --save    # label the failures  (check #1)
python scripts/eval_retrieval.py --save                    # before/after numbers (checks #3, #4)
```

The first writes nothing here. The second writes `failure-labels-dense.md`, the third writes
`eval-results.md`, both next to this file. Copy the numbers across into the tables below and
write the sentences in your own words.

---

## 1. The prediction, written before running anything

The one change is **hybrid retrieval**: keyword search (BM25) alongside the existing meaning
search, merged by Reciprocal Rank Fusion.

What I expect, and why:

- **It should fix the six exact-string questions.** `ERR-4032`, `security@northwind.example`,
  `Settings > Connections`, `code-freeze`, `MFA` and `collaboration day` are strings, not
  meanings. A dense embedding of a bare code is close to noise, while BM25 treats a rare
  token as a strong signal. These are labelled `favours: keyword` in `tests/eval_set.py`.
- **It should leave the four paraphrase questions alone.** The USB-stick, "hacked", receipt
  window and retirement questions share almost no words with their documents, so keyword
  search contributes nothing and RRF should let the dense ranking carry them. If any of these
  *regress*, RRF is letting keyword noise outrank a correct semantic hit, and
  `hybrid_candidates` is the knob to turn down.
- **It should not fix any GENERATION failure at all.** If the right document was already
  being fetched and the answer was still wrong, a better search cannot help. I expect
  `negative-carryover-payout` (an answer that requires reading a negative statement) and any
  wrongly-answered absent question to be unchanged. This is the honest limit of the change,
  and it is what check #4 is asking about.
- **Concretely:** hit-rate@3 should rise, driven almost entirely by the six keyword cases,
  and the still-broken list should be made up of generation failures rather than retrieval
  failures.

If the number goes up but the still-broken list is full of *retrieval* failures, the
hypothesis was wrong and the next change should be reranking or query rewriting instead.

---

## 2. The before-and-after number (check #3)

From `python scripts/eval_retrieval.py --save`. Measured over the 28 corpus questions; the
4 deliberately-absent questions are excluded because they have no expected document.

| Metric | dense (before) | hybrid (after) | Change |
|---|---|---|---|
| hit-rate@1 | | | |
| **hit-rate@3** | | | |
| hit-rate@5 | | | |
| MRR | | | |

One sentence in your own words on what that number means:

>

---

## 3. The failure labels (check #1)

From `python scripts/diagnose_failures.py --mode dense --save`. `RETRIEVAL` means the wrong
document was fetched, so the answer model never saw the right text. `GENERATION` means the
right document was fetched and the answer was still wrong.

| Case | Kind | The evidence, in one line |
|---|---|---|
| code-err4032 | | |
| exact-security-email | | |
| exact-settings-path | | |
| exact-policy-id | | |
| acronym-mfa | | |
| acronym-pim | | |
| paraphrase-usb | | |
| paraphrase-hacked | | |
| paraphrase-receipt-window | | |
| paraphrase-retirement | | |
| ambiguous-home-office | | |
| ambiguous-leave-days | | |
| ambiguous-notice-period | | |
| ambiguous-learning-budget | | |
| detail-sick-days | | |
| negative-carryover-limit | | |
| detail-carryover-expiry | | |
| detail-parental-leave | | |
| detail-notice-acme | | |
| track-remote-eligibility | | |
| track-internet-claim | | |
| track-nexora-classification | | |
| track-nexora-key-vault | | |
| handbook-probation | | |
| handbook-casual-leave | | |
| handbook-holidays | | |
| handbook-breach-hours | | |
| handbook-pip | | |
| absent-bonus | | |
| absent-dress-code | | |
| absent-azure-subscription-id | | |
| absent-azure-admin-limit | | |

Totals: ____ RETRIEVAL · ____ GENERATION · ____ PASS

**Pick one failure and write it out properly.** The mentor asks for a specific case with
evidence, so have one ready:

- Question:
- Which kind, and how you know:
- What was fetched (source, rank, which search found it):
- What the app answered:
- What would fix it:

---

## 4. What the change did NOT fix (check #4)

From the `NOT fixed by the change (still broken)` section of the eval output. This section
matters as much as the number above it — a change that fixes everything usually means the
test set was too easy.

| Case | Still failing because | Which kind | What would actually fix it |
|---|---|---|---|
| | | | |

If anything appears under `BROKEN by the change (a regression)`, record it here too rather
than quietly dropping it:

| Case | Was fine before, broken now | Likely cause |
|---|---|---|
| | | |

---

## 5. Was the prediction right?

Compare section 1 against sections 2 to 4. The eval script also prints a
`predictions from eval_set.py` block that grades each hypothesis for you.

- Predictions that held:
- Predictions that were wrong:
- What that tells me about this corpus:

---

## 6. The next one change (not for this week)

Based on the still-broken list, the single next change would be:

>

Written down now so that next week's measurement has something to test against.
