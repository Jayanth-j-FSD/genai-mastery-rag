# Week 11: the prediction, written before any request was sent to the model

Committed after the code and before the first live request of the cost measurement: `git log` shows the order. The code that checks it is `evals/cost_prediction.py`, run by `scripts/check_cost_prediction.py LABEL` on the result of `scripts/measure_cost.py`.

Every prediction is about a measured quantity; none says whether the improvement should ship, which is your decision. The thresholds below are the ones in that module, and a test fails if they differ.

The improvement being measured is `CONTEXT_STRIP_MIN_REPEATS=10`: the passages sent to the model lose every non-heading line that their own document repeats ten times or more (the handbook repeats a block of boilerplate under every section). The index and the search are untouched. It is off by default.

Where the numbers come from. The free screen, `python scripts/estimate_context_savings.py --bank 30 --seed 42` (no model calls; retrieval dense, top_k 4, 432 chunks), says the strip removes 17.9% of the prompt's characters on the 41 eval questions and 27.2% on 30 questions drawn from the Week 5 bank. It also says that retrieving one passage fewer (idea B) loses the answer on three eval questions, so B is not built, and that showing each line once per document (idea C) removes 9.8%, so it is not built either. Tokens are not characters: the removed lines tokenize about like the rest of the prompt, so the share of tokens removed is taken as the share of characters times a factor between 0.65 and 1.3. That gives a ratio of mean prompt tokens after to before of 0.77 to 0.88 on the eval questions and 0.65 to 0.82 on the bank, widened a little. The model's replies are written from the same facts, so their length should not move beyond sampling noise.

The measurement asks every question under three arms, interleaved with the order rotating: `before` (nothing changed), `after` (the strip on) and `before-2` (nothing changed again, the noise floor). Read on the questions every arm answered with the provider's own token counts:

| | prediction | primary metric |
|---|---|---|
| P1 | prompt tokens, eval questions: the mean after / before is between 0.75 and 0.90 | ratio of mean prompt tokens |
| P2 | prompt tokens, bank questions (read only when at least 20 were asked): between 0.62 and 0.85 | ratio of mean prompt tokens |
| P3 | noise floor: `before` and `before-2` send the same prompt tokens on at least 95% of the questions, and their means differ by less than 1% | questions with equal prompt tokens, difference of means |
| P4 | completion tokens: the mean after / before is between 0.85 and 1.15 | ratio of mean completion tokens |
| P5 | quality: no eval question that passes its rule checks under `before` fails them under `after`, except a question whose result also differs between `before` and `before-2` (that one is noise, not the idea) | eval questions that went from passing to failing |
| P6 | sources: on the three conflict questions (`ambiguous-leave-days`, `ambiguous-notice-period`, `ambiguous-learning-budget`) every document cited under `before` is still cited under `after` | documents lost |
| P7 | reach: the strip removed at least one character on at least 60% of the eval requests | requests with something stripped |

The prediction has FAILED if P1, P5 or P6 does not hold. P5 and P6 are the stop rule: if either fails, the setting stays off and the trade-off is reported instead of a saving. The others are reported held or not held, with no verdict on the whole. Each ratio is compared to two decimals, as the check prints it: a mean ratio of 0.904 prints as 0.90 and counts as inside a band that ends at 0.90. A dry run, a measurement that stopped early, and a measurement that did not ask the registered questions (41 eval questions, the three arms above) get no verdict at all. Every analysis not listed here is exploratory.
