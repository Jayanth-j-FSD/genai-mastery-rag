# Week 11: production, finding what happened, what it costs, and not breaking it twice

## The task (from the brief)

*Add proper logging to your app so you can find any past answer, then practise finding a planted bad answer from a vague complaint.
Measure your cost per request, make one improvement, and turn one real failure into a permanent test.* The track line for HR
policy: *find the wrong notice period in the logs.*

In plain words: until now the app answered and forgot. This week every request leaves a record of its steps, so a complaint
a week later can be answered from the log; the cost of a request is measured and cut once, with the answer quality checked
alongside; and a failure found in the log is kept as a test so it cannot quietly come back.

## Definition of done: the mentor's four questions

1. Can they find a specific past answer from the logs quickly?
2. Do the logs show time and cost per step, not just one total?
3. Did they measure cost per request and improve it?
4. Did they turn a real failure into a test that now guards against it?

Copied word for word from the brief.

## What was built, and which check it serves

| Piece | File | Serves |
|---|---|---|
| A request id and one timed record per step (embedding the question, each search, the model call), with the model step's time split into time at the provider and time waiting for the rate limit, and the tokens the provider reported | `app/observability.py`, hooks in `app/rag/pipeline.py`, `retriever.py`, `generator.py` | 2 |
| The request log: one JSON line per answered request, now with the request id, the steps, the tokens, the documents listed as sources and why it refused; a failed request goes to `errors.jsonl` (kind of failure and HTTP status, never the message or the question); safe for several threads and several processes | `app/tracing.py` | 1, 2 |
| The request id on every `/ask` answer and on every error the API maps to a status (400, 429, 502) in an `X-Request-ID` header, an optional `X-Caller-ID`, and the id printed by `scripts/ask.py` | `app/main.py`, `scripts/ask.py`, `scripts/ask_batch.py` | 1 |
| Finding a request: by words, an answer pattern, a time window, the document cited or retrieved from, status, channel, id prefix, how slow, how costly; groups identical answers; reads one request step by step, with each step's time, tokens and dollars at the prices you state, and each passage in full with `--full` | `scripts/find_requests.py`, `evals/logsearch.py` | 1, 2 |
| The cost report: per step across many requests (time, provider time apart from waiting, tokens), per request (tokens first, then time, then dollars at prices you state), two logs side by side, a saved measurement | `scripts/cost_report.py`, `evals/costreport.py` | 2, 3 |
| The support drill: a synthetic log with one wrong notice answer planted in it, a vague complaint, and a five-guess checker | `scripts/make_drill.py`, `scripts/check_drill.py`, `evals/drill.py` | 1 |
| The one improvement: take the lines a document repeats out of what the model is shown (`CONTEXT_STRIP_MIN_REPEATS`, off by default) | `app/rag/generator.py`, `app/config.py` | 3 |
| Choosing it for free: three ideas screened on the 41 eval questions without a model call | `scripts/estimate_context_savings.py`, `evals/context_savings.py` | 3 |
| Measuring it: the same questions under several arms, interleaved, with the unchanged arm asked twice as the noise floor, every request logged like a user's | `scripts/measure_cost.py`, `evals/cost_run.py` | 3 |
| The prediction, written before any request, and the check that turns it into arithmetic | `docs/week11/prediction.md`, `evals/cost_prediction.py`, `scripts/check_cost_prediction.py` | 3 |
| A real failure into a test: the logged answer must fail the case and a correct answer must pass it, or the tool refuses | `scripts/failure_to_test.py`, `evals/logged_failures.json`, `tests/fixtures/log_regressions/` | 4 |

Nothing about the four answer keys changed: `pipeline.answer` still returns `answer`, `sources`, `grounded`, `retrieval_mode`, and
`POST /ask` still returns those four in its body. The request id travels in a header. A line in the log written before this week
is still a complete record and every tool reads it; it just has no steps.

## Run it

```powershell
.\.venv\Scripts\python.exe scripts\ask.py "How much notice must a permanent employee give before resigning?"   # prints the request id
.\.venv\Scripts\python.exe scripts\find_requests.py --text notice                                          # find it again
.\.venv\Scripts\python.exe scripts\find_requests.py --id <id> --show                                       # its steps as a table
.\.venv\Scripts\python.exe scripts\cost_report.py --price-in <usd> --price-out <usd> --price-source "<where>"   # time and tokens per step, dollars per request

.\.venv\Scripts\python.exe scripts\make_drill.py                                                          # build the support drill
.\.venv\Scripts\python.exe scripts\find_requests.py --drill <drill id> --text notice --distinct-answers
.\.venv\Scripts\python.exe scripts\check_drill.py <drill id> <request id>                                 # five guesses

.\.venv\Scripts\python.exe scripts\estimate_context_savings.py --bank 30 --seed 42                         # the free screen, no model calls
.\.venv\Scripts\python.exe scripts\measure_cost.py --label w11 --model <model> --bank 30 --seed 42         # the measurement (use --dry-run first, and --label w11-smoke for a first look)
.\.venv\Scripts\python.exe scripts\measure_cost.py --label w11 --model <model> --bank 30 --seed 42 --resume   # carry it on after a stop or a failed request
.\.venv\Scripts\python.exe scripts\check_cost_prediction.py w11
.\.venv\Scripts\python.exe scripts\cost_report.py --show w11 --price-in <usd> --price-out <usd> --price-source "<where>"

.\.venv\Scripts\python.exe scripts\failure_to_test.py <id> --expect-source <doc> --expect-contains "<phrase>" --corrected-from <id of a good answer>
```

The free screen needs the local embedding model (`scripts\download_model.py`). The measurement needs a model with free quota; name
it, never an alias. Every script that can spend quota has a way to look first: `--dry-run` for the measurement, no `--yes` for the
failure tool.

Two things about the measurement, because its quota cannot be refilled that day. It always asks the 41 base eval questions (plus the bank
sample you ask for): a failure you convert into a test later is never added to it, so converting one before or after changes nothing about what was
registered. And it can be carried on: it stops on the daily quota, on three provider failures in a row, on `--max-calls`, or on Ctrl-C, and a
request that failed is kept as a failed row; `--resume` keeps every answered request, asks the failed ones again and never asks an answered one twice
(a copy of the result it carries on is kept beside it). A resume is checked before any file is touched: it refuses, and leaves the saved result where it
was, only when the model, the arms, the questions, the settings or the code and documents that decide the answers (`app`, the scoring and measuring modules, the
corpus) differ from the first part's; a commit that touches only tests, docs, saved results or other scripts does not stop it. A setup problem (no API key,
nothing indexed) stops at the first request with the app's own words. The measurement and its resume have to fit in the model's day together: about 213
requests for 71 questions under 3 arms.

The prediction was registered for one set of conditions: retrieval dense, `TOP_K=4`, local embeddings (`EMBED_PROVIDER=local`), chunks of 800 characters with
120 of overlap, exact search, no dedupe and no boilerplate strip, 432 chunks, and the 41 eval questions plus 30 bank questions drawn with seed 42. A real run
under other settings stops before the first request and names each difference (`--allow-unregistered` measures anyway, and the prediction check then gives no
verdict); a finished measurement under other settings, another index or other questions gets no verdict either.

## What a request log line holds

One line per answered request in `data/traces/traces.jsonl`. The keys Weeks 3 to 5 wrote are unchanged (`trace_id`, `ts`, `question`,
`retrieved`, `answer`, `grounded`, `config`). This week adds, all optional:

| Key | What it says |
|---|---|
| `request_id` | 16 hex digits; the first 8 are the `trace_id` the older lines have |
| `started_at`, `ts_utc`, `total_ms` | when it started (local and UTC) and how long the whole request took |
| `channel`, `caller` | how it arrived (`api`, `cli`, `batch`, `measure`) and the optional `X-Caller-ID` |
| `spans` | one record per step: `span_id`, `name`, `kind` (`embed`, `retrieve`, `model`), `start_ms`, `duration_ms`, `status`, `error` (the class of the exception when the step failed) and `cold` (the first step of its kind in a process). The embed step adds `provider`, `cost_usd` (0.0 for a local model) and `cost_basis`; the search step `mode` and `top_k`; the model step `model_requested`, `model_served`, `provider_ms`, `wait_ms`, `attempts`, `tokens_known`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `cached_tokens`, `reasoning_tokens`, `cost_usd` and, when a price is set, `prices` |
| `usage` | `model_calls`, the request's tokens (the sum of its model steps), `provider_ms`, `wait_ms`, and `tokens_known`, false when any call reported none: the sums are then lower bounds |
| `sources`, `status`, `refusal_cause` | the documents the app listed as sources (when the model wrote no `[source: ...]` tag the app lists every retrieved document, so `find_requests.py` reads what an answer CITED from its tags and shows the listed ones apart), `ok` or `refused`, and why it refused (`no_chunks`, `below_min_relevance`, `empty_reply`, `model_idk`, `context_all_repeated`, or `unknown` when a refusal reached the end with no cause noted) |
| `index_id`, `prompt_sha`, `chars` | which index answered (the number of chunks and a short hash of the documents: an index rebuilt by another process with the same number of chunks is not noticed until this process restarts), a hash of the instructions, and how many characters of the prompt were instructions, passages and question, and how many were stripped |

Two rules the log keeps, because a log that gets them wrong is worse than none. Spans are steps, not groups of steps, so they do
not overlap and their durations add up to at most the request's time. And the model step keeps the waiting apart: on a free tier most
of a model call's wall time can be the app sleeping to stay under a rate limit, which no change to the prompt will shorten.

`cost_usd` is filled only when a price is set (`PRICE_INPUT_PER_MILLION`, `PRICE_OUTPUT_PER_MILLION`) and then travels with the prices
used, labelled an assumption. With no price it is `null`: unknown is not free.

## What is logged, what is not, and who can see it

- **Logged:** `POST /ask`, `scripts/ask.py`, `scripts/ask_batch.py`, and each request of `scripts/measure_cost.py`. **Not logged:** the agent,
  race, eval and diagnose runs (they have their own saved results), and an empty question.
- `traces.jsonl` holds the question, the full text of every retrieved passage and the answer. That is private data: the folder is ignored
  by git, and the same goes for `data/measure/` and `data/drill/`. A test fails if one of them is not ignored, or if anything under
  `data/` other than the corpus is tracked.
- `errors.jsonl` (beside the traces) holds, for a request that failed, its id, when, the kind of failure, the HTTP status the API sent and
  the steps it finished. Never the exception's message (a provider error can echo request details) and never the question, only its length
  and a short hash, so a known question can be matched without the log holding it.
- What a measurement commits holds no passage text and no question text from the log: numbers and names only. A failure fixture is different on
  purpose: it keeps the question and the two answers of the request you convert (real text, written to the files as ASCII escapes), and only document
  names and scores of the passages. The tool says so when you pass `--yes`: read what it wrote before you commit it.
- A request that fails with something the API does not map (an HTTP 500) is in `errors.jsonl` with its id but its response carries no `X-Request-ID`
  (find it with `find_requests.py --status error --since ...`); a request the API rejects before the pipeline (a malformed body, HTTP 422) leaves no record.
- There is no automatic deletion: logs grow until you delete the file. Writing is thread-safe in one process and, with an operating-system
  lock on a side file, safe across processes; a writer that cannot get the lock within two seconds drops its line, prints a warning and
  counts it in memory (`tracing.dropped_records()`; nothing reads that count yet), instead of making the user wait.
- Logging never breaks answering: every piece that runs while a request is answered catches its own failure, says so once and carries on.

## The support drill

`make_drill.py` writes about 3000 synthetic requests over four weeks, shaped like the real ones (the same keys, steps and kinds of numbers,
real passages of the corpus), a vague complaint, and a hash that lets `check_drill.py` tell whether a guess is the planted request. Among the
notice-period answers, which differ by company and status, exactly one states a figure that the document it cites does not state: in some drills a figure no
document states, in the others one the other document does. Each question gets answers that really answer it, in several wordings. The planted answer is worded
like right answers that state a different, right figure; some right answers are as rare as it is and sit inside the complaint's window and under the document the
complaint names (by the file name the log cites, so a `--cited` filter can be written from it); and its day, hour and channel are drawn like everyone else's. So
the rarity of an answer, its wording and its place in the log do not give it away. An unusual figure can, in the drills where no document states it; whether an
answer is wrong is settled only by reading the document it cites, and `find_requests.py --id <id> --show --full` prints the passages the log shows for that
request without cutting them. The kit refuses to build if its own decoys state something the corpus no longer says, or if it did not plant exactly one wrong answer. Every request in a drill says it is synthetic, and so does the complaint. The checker tells a
log that was edited from a wrong guess and does not charge for it, and does not charge twice for the same wrong id. It is an honour system, and says so.
Finding the request and writing down what you looked at is yours.

## The improvement, and how it was chosen

The log showed what the prompt is made of: mostly the retrieved passages, and a lot of those are lines the handbook repeats under every
section. `CONTEXT_STRIP_MIN_REPEATS=10` takes out of what the model is shown every non-heading line that its own document repeats that many
times. The index and the search are untouched, so no re-ingest is needed and the same passages are retrieved. Three ideas were screened for
free on the 41 eval questions before any request: this one, retrieving one passage fewer, and showing each line once per document (see
`CHANGES.md` for what the screen found). The prediction was committed before the first live request; the measurement and the verdict on
it are in `findings.md`.

## Turning a failure into a test

`failure_to_test.py` takes one logged request. You say what a correct answer looks like and give a correct answer (quoted from another real
logged request, or written by hand). It replays both before writing anything: the logged answer must fail the case and the correct answer
must pass it, or it refuses. It also refuses a case that names no phrase a correct answer states (a case that only forbids one wording passes every
other wrong answer), a document that is not in the corpus, and an id that is not a plain file name. It says whether the failure was RETRIEVAL or GENERATION
using the same whole-word phrase rule the checks use. The test suite replays every fixture against the LIVE case as well as against the fixture's own copy, so
loosening a case later is caught. What it cannot prove: that a correct answer you typed is one the model would really give; only a live run does
(`run_evals.py --only <id>`). It adds one case to `evals/logged_failures.json` and a fixture to `tests/fixtures/log_regressions/`; the
fixture is replayed offline on every run of the test suite, in both directions. A worked example built from a real failure in the log
(the notice question answered "I don't know" while two documents answer it) ships as a fixture only; it is labelled as drafted by the tool,
for you to review, and adds no case to the eval set. Converting a failure of your own, and saying why it is real, is yours.

## A short glossary (terms, not answers)

- **Trace and span**: a trace is the story of one request; a span is one step of it, with when it started and how long it took.
- **Request id**: a short unique name for one request, returned to the caller so a complaint can quote it.
- **Noise floor**: how much two runs of the same thing differ by chance. A difference smaller than that is not a result.
- **A/A arm**: an arm that changes nothing, asked in addition to the arm that does, to measure the noise floor.
- **Input and output tokens**: what you send and what the model writes; priced separately, output higher.
- **Prompt caching and semantic caching**: reusing the provider's work on an identical prompt prefix, and reusing an answer to a question that means the same as an earlier one. Neither is built here.
- **Data flywheel**: failures found in production become tests, tests guard the next change, the next change finds new failures.

## What is not built

OpenTelemetry or hosted-tracer export, caching of either kind, model routing, a second-model fallback, fine-tuning, and any automatic
log retention. `CHANGES.md` says why each was left and what the log already holds toward it.

## The part that is yours

In `findings.md`: the drill write-up (what you looked at and why the answer was wrong), the prices you use and where they come from, your reading of
what the measurement means and whether the improvement ships, the failure you convert and why it is real, and the 10x plan (what breaks first at ten
times the traffic). Nothing here writes them for you.
