# Week 11: findings

This is the file the mentor reads. Every output below was printed by the command shown above it, so it can be run again (the commands
that read a log read the project's own, `data/traces/traces.jsonl`, or the logs of the measurement, `data/measure/w11/`, which are not
committed because they hold the questions and the passages). The sections marked *Yours to write* are blank on purpose: the brief asks for
your own judgement, and nothing else in this folder supplies it.

## 1. Finding a past answer in the logs (check 1)

The real log has the request the notice question got on 2026-09-25, found by the first characters of its id. It was logged before this week, so it has
no steps; the tool says so instead of guessing.

Command: `python scripts/find_requests.py --id 503834ae --show`

```text
scanned 9 records in 7 ms from data/traces/traces.jsonl, data/traces/errors.jsonl
1 matched

request 503834ae  (trace line 4 of traces.jsonl)
  time      2026-09-25 01:56   channel -
  status    refused
  question  How much notice must a permanent employee give before resigning?
  answer    I don't know based on the provided documents.
  cited     (nothing: the answer has no [source: ...] tag)
  retrieved 4 passages:
    1.       Synthetic_HR_Policy_RAG_Test_Dataset.md  score 0.2238  - Requests should normally be submitted through the employee portal before the relevant d~
    2.       Synthetic_HR_Policy_RAG_Test_Dataset.md  score 0.2238  - Requests should normally be submitted through the employee portal before the relevant d~
    3.       Synthetic_HR_Policy_RAG_Test_Dataset.md  score 0.2238  - Requests should normally be submitted through the employee portal before the relevant d~
    4.       Synthetic_HR_Policy_RAG_Test_Dataset.md  score 0.2238  - Requests should normally be submitted through the employee portal before the relevant d~
  model     asked gemini-flash-latest, answered by None   index -
  steps     no steps recorded (a line written before Week 11 has none)
```

Narrowing a log is the same filters in a different order: words, a time window, the document the answer cited, how many different answers there were.

Command: `python scripts/find_requests.py --text notice --distinct-answers`

```text
scanned 9 records in 1 ms from data/traces/traces.jsonl, data/traces/errors.jsonl
4 matched
3 distinct answer(s) among 4 answered requests

 count   share  first seen       example id       answer
     2   50.0%  2026-09-25 01:56 503834ae         I don't know based on the provided documents.
     1   25.0%  2026-09-15 17:53 34356af6         A permanent employee must provide 30 calendar days of written notice before resigning. [source: Acm~
     1   25.0%  2026-10-11 00:50 8705a1c3         Based on the provided documents, the notice period required for a permanent or confirmed employee b~
```

### The support drill

`python scripts/make_drill.py` builds a log with one wrong notice answer planted in it and prints a vague complaint; `python scripts/check_drill.py <drill id> <request id>`
tells you whether you found it. Nothing here shows a solved drill, because solving it is the exercise.

**Yours to write:** which request you found, what was wrong with its answer, and what you looked at to be sure (which filters, in which order, which document you
compared it with, how long it took).

## 2. Time and cost per step (check 2)

The measurement below logged every request like a user's, so each line of `data/measure/w11/before/traces.jsonl` has its steps. This is the
report over the `before` arm: tokens first, then time, then the steps; the model step's time is split into time at the provider and time spent waiting for the
rate limit. No price is stated here, so no dollars.

Command: `python scripts/cost_report.py --log data/measure/w11/before/traces.jsonl`

```text
reading data/measure/w11/before/traces.jsonl: 71 records

71 answered requests; the provider reported tokens for 71
  prompt tokens             mean 683.2, median 696.0, max 870.0   (n 71)
  completion tokens         mean 43.1, median 35.0, max 174.0   (n 71)
  total ms                  mean 7,091.0, median 1,234.9, max 53,671.7   (n 71)
  model ms at the provider  mean 3,197.5, median 1,094.0, max 53,469.0   (n 71)
  model ms waiting          mean 3,849.1, median 0.0, max 46,175.0   (n 71)
  waiting is 55% of the model time (rate limit and back-off; a shorter prompt does not shorten it)
  no price stated, so no dollars are shown (pass --price-in and --price-out above 0, and --price-source)

step by step (times in milliseconds):

71 requests recorded their steps
step            kind           n   mean ms   median      max      p95   share  provider   waited  tokens in    out
generate        model         71     7,049    1,215   53,650        -     99%     3,197    3,849        683     43
search          retrieve      71        28       16       79        -      0%         -        -          -      -
embed_query     embed         71        12        4      205        -      0%         -        -          -      -
3 steps were the first of their kind in a process (cold start) and are included; --skip-cold leaves them out
```

The same with the first step of each kind in the process left out (one-time start-up costs):

Command: `python scripts/cost_report.py --log data/measure/w11/before/traces.jsonl --skip-cold`

```text
reading data/measure/w11/before/traces.jsonl: 71 records

71 answered requests; the provider reported tokens for 71
  prompt tokens             mean 683.2, median 696.0, max 870.0   (n 71)
  completion tokens         mean 43.1, median 35.0, max 174.0   (n 71)
  total ms                  mean 7,091.0, median 1,234.9, max 53,671.7   (n 71)
  model ms at the provider  mean 3,197.5, median 1,094.0, max 53,469.0   (n 71)
  model ms waiting          mean 3,849.1, median 0.0, max 46,175.0   (n 71)
  waiting is 55% of the model time (rate limit and back-off; a shorter prompt does not shorten it)
  no price stated, so no dollars are shown (pass --price-in and --price-out above 0, and --price-source)

step by step (times in milliseconds):

71 requests recorded their steps
step            kind           n   mean ms   median      max      p95   share  provider   waited  tokens in    out
generate        model         70     7,107    1,198   53,650        -     99%     3,201    3,904        684     43
search          retrieve      70        28       16       79        -      0%         -        -          -      -
embed_query     embed         70         9        4       56        -      0%         -        -          -      -
3 steps were the first of their kind in a process (cold start) and are left out
```

**Yours to write:** the prices you state for dollars (`--price-in`, `--price-out`) and where you read them (`--price-source`), and what the step table says about where
the time goes and what would shorten it.

## 3. Cost per request, measured and improved once (check 3)

The one improvement is `CONTEXT_STRIP_MIN_REPEATS=10`: take out of what the model is shown every line that its own document repeats ten times or more. It was chosen
from three ideas screened for free, before any request:

Command: `python scripts/estimate_context_savings.py --bank 30 --seed 42`

```text
free screen: 41 eval questions and 30 from the Week 5 bank (seed 42), retrieval dense, top_k 4, 432 chunks, no model calls
chars = mean prompt characters (instructions + passages + question) before the idea; after = with it; saved = the share removed

idea                                 chars   after   saved  median     max   no saving   screen

A strip lines repeated 10+ times      3042    2418   21.8%   16.3%   77.7%    11 of 71   passes
B retrieve 3 passages, not 4          3042    2456   19.2%   18.7%   30.4%     0 of 71    FAILS
C show each line once per document    3042    2763    9.8%    7.9%   47.6%    18 of 71   passes

what a FAILS idea loses (a document the case needs, or a fact string that was in the prompt):
  B retrieve 3 passages, not 4: paraphrase-usb no longer shows a passage with the answer from ['Nexora_Tech_Azure_Cloud_Data_Access_Policy.md']
  B retrieve 3 passages, not 4: ambiguous-learning-budget no longer shows a passage with the answer from ['benefits.md']
  B retrieve 3 passages, not 4: detail-sick-days no longer shows a passage with the answer from ['Acme-Leave-Policy-2026.md']
  B retrieve 3 passages, not 4: paraphrase-usb no longer shows ['must not']
  B retrieve 3 passages, not 4: ambiguous-learning-budget no longer shows ['1,000']

A strip lines repeated 10+ times, by kind of question:
  eval questions   41   mean saved 17.9%, mean prompt 3131 to 2617 characters
  bank questions   30   mean saved 27.2%, mean prompt 2921 to 2148 characters

Characters are not tokens: tokens follow characters to a first approximation and scripts/measure_cost.py measures them.
```

The prediction was written and committed before the first live request (`docs/week11/prediction.md`). The measurement asked every question under three arms, interleaved,
with the order rotating: `before`, `after` (the strip on) and `before-2` (nothing changed again, the noise floor).

Command: `python scripts/cost_report.py --show w11`

```text
model gemini-3.1-flash-lite-preview (served: gemini-3.1-flash-lite-preview), 71 questions x 3 arms, 219 model calls

arm            requests errors refused  prompt tok  compl tok provider ms  wait ms  stripped   passed
before               71      0      11       683.2       43.1        3197     3849         0 37 of 41
after                71      0       9       581.8       43.9        3649     2581       616 38 of 41
before-2             71      0      11       683.2       43.1        3522     2708         0 37 of 41

after against before on 41 eval questions both answered: pass to fail none; fail to pass ['negative-carryover-limit']

before-2 against before on 41 eval questions both answered: pass to fail none; fail to pass none

no price stated, so no dollars are shown (pass --price-in and --price-out above 0, and --price-source)
```

The two untouched arms against each other (the noise floor), then the unchanged arm against the improved one, on the same questions:

Command: `python scripts/cost_report.py --compare data/measure/w11/before/traces.jsonl data/measure/w11/before-2/traces.jsonl`

```text
71 of 71 paired questions had token counts in both logs; model gemini-3.1-flash-lite-preview
                                      before                before-2    b / a
prompt tokens                          683.2                   683.2     1.00
completion tokens                       43.1                    43.1     1.00
total ms                             7,091.0                 6,273.6     0.88
provider ms                          3,197.5                 3,522.1     1.10
waiting ms                           3,849.1                 2,708.0     0.70
```

Command: `python scripts/cost_report.py --compare data/measure/w11/before/traces.jsonl data/measure/w11/after/traces.jsonl`

```text
71 of 71 paired questions had token counts in both logs; model gemini-3.1-flash-lite-preview
                                      before                   after    b / a
prompt tokens                          683.2                   581.8     0.85
completion tokens                       43.1                    43.9     1.02
total ms                             7,091.0                 6,274.3     0.88
provider ms                          3,197.5                 3,648.9     1.14
waiting ms                           3,849.1                 2,580.8     0.67
```

And the prediction against the numbers:

Command: `python scripts/check_cost_prediction.py w11`

```text
P1  held          mean prompt tokens 701.0 before, 617.4 after: ratio 0.88 on 41 questions, band 0.75 to 0.90
P2  held          mean prompt tokens 659.0 before, 533.2 after: ratio 0.81 on 30 questions, band 0.62 to 0.85
P3  held          the same prompt tokens on 71 of 71 questions (100%, need 95%); the means differ by 0.00% (need under 1%)
P4  held          mean completion tokens 38.9 before, 39.9 after: ratio 1.02 on 41 questions, band 0.85 to 1.15
P5  held          0 eval questions went from passing to failing under after: none, on 41 compared
P6  held          documents cited before and no longer after: none
P7  held          the strip removed something on 30 of 41 eval requests (73%, need 60%)

The prediction as a whole: did not fail (P1, P5 and P6 held). Whether the improvement ships is your decision.
```

**Yours to write:** what the before and after numbers mean, whether the improvement ships, and why; and what the noise floor says about how much of any difference to believe.

## 4. A real failure turned into a test (check 4)

The worked example is a real failure from the log above: the notice question answered "I don't know" while two documents answer it (four copies of one boilerplate
passage filled every slot). The tool replays it before writing anything, and says what kind of failure it was:

Command: `python scripts/failure_to_test.py 503834ae --id log-demo-notice-idk --problem-type crowded-handbook --expect-source Acme-Employment-Terms-2026.md --expect-source Synthetic_HR_Policy_RAG_Test_Dataset.md --expect-contains "30 calendar days" --expect-contains "60 calendar days" --corrected-from 34356af6 --cases data/measure/scratch-logged-failures.json --fixtures data/measure/scratch-fixtures`

```text
case log-demo-notice-idk: How much notice must a permanent employee give before resigning?
  the logged answer (2026-09-25 01:56:09): I don't know based on the provided documents.
  it fails: refusal (refused a question the documents do answer); cites_expected_source (cited nothing, expected one of ['Acme-Employment-Terms-2026.md', 'Synthetic_HR_Policy_RAG_Test_Dataset.md']); has_expected_fact (contains none of ['30 calendar days', '60 calendar days'])
  a correct answer passes: A permanent employee must provide 30 calendar days of written notice before resigning. [source: Acme-Employment-Terms-20
  what kind of failure: RETRIEVAL, the passage with the answer was not among those the model saw

Nothing written. Run again with --yes to add the case to data/measure/scratch-logged-failures.json and the fixture to data/measure/scratch-fixtures.
```

It was written (with `--yes`, into a scratch folder, so the eval set stays 41 cases) as `tests/fixtures/log_regressions/log-demo-notice-idk.json`, labelled as drafted by the
tool for you to review. Every fixture is replayed offline on every run of the test suite: the logged answer must fail its case and a correct answer must pass it, and for a
retrieval failure the real local embedder checks that the passage the failure missed is retrieved now.

**Yours to write:** the failure of your own that you converted (`python scripts/failure_to_test.py <id> ...`), why it is a real failure and not a test of the tool, and what the
tool told you about it (retrieval or generation).

## 5. The 10x plan

**Yours to write:** what breaks first at ten times the traffic, in what order, what you would measure to know, and what you would change first. The log in section 2 is the
evidence for the first part.

## 6. What was not verified

- Characters are not tokens. The free screen in section 3 counts characters; the measurement counts tokens the provider reported.
- The measurement is one model on one day. Its noise arm bounds the noise inside that day; it does not say what another model or day would do.
- The drill is synthetic and an honour system; it says what a drill looks like, not how your real log would.
- Nothing here was measured against a real price; the dollar figures are yours to add.
