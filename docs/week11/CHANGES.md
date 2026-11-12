# Week 11: what changed, and why

Branch `week-11-production`, built on `week-10-multi-agent`. Every change to an existing file is additive: a line written
before this week still reads, `pipeline.answer` still returns its four keys, `POST /ask` still returns four keys in its body,
a trace id is still eight hex digits, and a case without the new keys is scored exactly as before. What was measured, and
the verdict on the prediction, are in `findings.md`; the numbers here are only the ones a script printed.

**Left for you.** The drill write-up, the plan for 10x the traffic, whether the improvement ships, the prices you state and where they come from,
and the failure you convert into a test and why it is real are blank in `findings.md`.

## What was added

- `app/observability.py`: the request and its steps. A request context that always closes and keeps its id readable after it ends;
  steps (spans) that never overlap, timed with a monotonic clock; a model step that keeps provider time, waiting time, attempts, tokens
  (only when the provider reported them) and cost (only when a price is set); notes for the refusal cause, the documents cited, the
  index, a hash of the instructions and the split of the prompt. Every function that runs while a request is answered catches its own
  failure, says so once and carries on.
- `app/tracing.py`: one line per answered request with the new optional keys, a thread lock plus an operating-system lock on a side file
  so two processes cannot write into each other, repair of a line cut off by a crash, `errors.jsonl` for failed requests, and readers
  that take another log's path. The record builder was factored out of `log_trace` so the drill builds its lines from the same code.
- `app/main.py`, `scripts/ask.py`, `scripts/ask_batch.py`: the request id in an `X-Request-ID` header on answers and on every mapped
  error, an optional `X-Caller-ID`, and the channel a request arrived by.
- `app/rag/pipeline.py`, `app/rag/retriever.py`: the request context around `answer`, the timed steps (embedding the question, each search, the model call), the
  error record of a request that failed, the id of the index that answered, the refusal cause and the documents cited and listed.
- `app/llm.py`: the per-call record says whether the provider reported usage at all (`usage_reported`), so a call that reported nothing
  is not read as a call that cost nothing. The five-key usage dict is untouched.
- `scripts/find_requests.py`, `evals/logsearch.py`: finding a request (`--full` prints a passage whole; a log of a drill or a dry run carries a banner; a log that
  cannot be read is an error line).
- `scripts/cost_report.py`, `evals/costreport.py`: the cost report.
- `scripts/make_drill.py`, `scripts/check_drill.py`, `evals/drill.py`: the support drill.
- `CONTEXT_STRIP_MIN_REPEATS` in `app/config.py` and `app/rag/generator.py` (`strip_context` and its helpers), `evals/runner.py` (the cache key):
  the improvement.
- `scripts/estimate_context_savings.py`, `evals/context_savings.py`, `evals/bank.py`: the free screen and the question bank sample.
- `scripts/measure_cost.py`, `evals/cost_run.py`: the measurement (`--resume` carries a stopped one on, `--allow-unregistered` measures under settings the
  prediction was not registered for).
- `docs/week11/prediction.md`, `evals/cost_prediction.py`, `scripts/check_cost_prediction.py`: the prediction and its check.
- `.gitignore`: the folders that hold request text, the copies a resume and a forced run keep beside a result, and the failure tool's temporary files.
- `tests/unit/_testkit.py`: `isolated_index` pins the context strip off, so a value in `.env` cannot decide what a test sees.
- `scripts/failure_to_test.py`, `evals/logged_failures.json` (created by the tool when a failure is converted), `tests/fixtures/log_regressions/`,
  `forbid_contains` in `evals/checks.py`, `load_logged_failures` in `evals/cases.py`: a failure becomes a test.

## Decisions

1. **One line per request, new keys optional.** The Week 5 sampling and `inspect_traces.py` count lines and read the old keys, so the line
   gains keys and loses none. An old line is a first-class record: no steps, and the tools say "no steps recorded" instead of guessing.
2. **Failed requests are a separate log with no text.** A provider error can echo request details and a question can be private, so
   `errors.jsonl` keeps the class, the HTTP status the API sent, the steps finished, and only the length and a short hash of the question.
   A test makes a key-shaped string the exception message and checks it never reaches the file. The status the log records is the one
   the API really sent: a test runs every mapped exception through the API and compares.
3. **The request id goes in a header.** The body of `/ask` is pinned at four keys. The id is also minted for errors, because the
   request a support person most needs to find is the one that failed.
4. **Steps are leaves and the model step separates waiting.** A step is one thing, so durations add up to at most the request's time.
   `duration_ms` is wall time, `provider_ms` is time inside the provider and `wait_ms` is the rate-limit sleep and error back-off: on
   the free tier most of the wall time of a model call can be waiting (in the saved Week 7 race, 480.9 of 601 wall seconds were rate-limit waits). The first step of each kind in a process is
   marked `cold`, because it pays one-time costs; the report counts it and can leave it out.
5. **Tokens are facts, dollars are assumptions.** The provider reports tokens; a price is something you state. `cost_usd` is filled only
   when a price is set and then carries the prices used; the report scripts compute dollars again from tokens and the prices on the command
   line and never read the `PRICE_*` settings, so one log cannot print two different costs on two machines. A request whose provider
   reported no tokens is left out of token and dollar figures and counted; it is never averaged in as zero.
6. **The log is safe to write from several places.** Unlocked concurrent appends lost lines on this Windows machine when several writers ran at once, in a test made
   while the week was designed (it was not kept as a script, so no figure is quoted here); with a lock none were lost, and the tests here show that with real processes. Both logs go through one append function: a thread lock, an
   operating-system lock on a side file (`msvcrt` on Windows, `fcntl` elsewhere, with a two second limit after which the line is dropped,
   a warning printed and a counter kept), and a newline repair for a line cut off by a crash. The locking is tested with threads and with
   real processes, including one that holds the lock.
7. **Logging never breaks answering.** A bug in the recorder, the price lookup, the id computation or the file write must not turn a paid
   answer into an error. Tests break each of those on purpose and check the user still gets the answer, with the four keys.
8. **Prices never come from a table.** The project ships none: it would go stale and read as a fact. They are stated on the command line with
   their source, and printed under every dollar figure.
9. **The improvement is prompt-side and off by default.** The Week 8 boilerplate strip works on the index and changes what is retrieved;
   cost is about what the model is sent, so this one leaves retrieval alone and is applied to the passages in `generate_answer`. The repeats
   are counted once per index from the stored chunks (a line in the 120 characters two neighbours share is counted twice, so an ordinary line is
   very unlikely to reach ten repeats that way). A passage with nothing left is dropped, and when nothing at all
   is left the app refuses without asking the model (refusal cause `context_all_repeated`), because that is what the model would answer. The
   sources listed are the documents the model was actually shown. The eval answer cache is keyed by what the model is shown, and the setting
   joins the key only when on, so every earlier cached answer stays valid.
10. **Choose by a free screen, then pre-register.** Three ideas were screened on the 41 eval questions with retrieval only (free, local, exact):
    the strip (A), retrieving one passage fewer (B, `TOP_K - 1`) and showing each line once per document (C, screened and not built). The screen
    reports characters removed and whether the passage or the fact string the answer needs is still there. B loses the answer on three eval
    questions, so it is out; A and C pass, A removes about twice as much as C and leaves retrieval alone. A first draft of the screen counted a
    word in handbook boilerplate as the answer to a Nexora question; only passages of the expected documents count now. The numbers are in
    `findings.md` and `prediction.md`.
11. **The prediction is arithmetic, written first.** `docs/week11/prediction.md` was committed before any request; `evals/cost_prediction.py`
    turns it into held / not held, compares ratios as printed, gives no verdict to a dry run, a partial measurement or one that did not ask
    the registered questions, and treats a prediction it could not read as undecided, not failed. The stop rule: if a question that passes
    before fails after (and is not noise), or a conflict question loses a cited document, the setting stays off and the trade-off is reported.
12. **The measurement is interleaved, with a noise arm.** For each question every arm is asked in turn and the order rotates, so a
    provider that slows down or a model swapped behind an alias hits every arm equally. `before` is asked twice: the difference between two
    identical arms is the noise floor. Eval questions are scored by the Week 6 rules as they are asked, so a saving is never read without
    "and did it still answer".
13. **The drill is built to be fair, and to be honest about being synthetic.** See the README. The rule that says an answer is wrong is written
    apart from the generator and reads the allowed figures from the corpus, and the build stops if the decoys and the corpus disagree. The
    answer is not stored, only a commitment; that makes it an honour system, and the checker says so.
14. **A failure becomes a test only if it proves itself.** The tool replays before writing: the logged answer must fail the case and a
    correct answer must pass it. A new check, `forbid_contains`, sits beside the old ones (whole words, case-insensitive; it cannot tell
    "45 days" from "not 45 days", which is said where it is defined), the new case file is separate from the Week 5 regressions, and
    a case with no expectations is refused at load because it would silently become a refusal case and pass the failure it came from.

15. **A resume never leaves a label without its result, and only a change to what decides the answers stops it.** The check runs before any file is touched and, when
    it refuses, says what differs and leaves the saved result where it was. A copy of the result is kept beside it, not a move, so a stop at any moment leaves the
    label with its result. What is compared is a hash of the files under `app`, the scoring and measuring modules and the corpus, not the commit: a test, a doc, a
    saved result or a converted failure committed between a stop and its resume does not stop it. A last save that fails is an error with the way on, never a
    "saved".
16. **The prediction is registered with its conditions.** The bands come from a screen at retrieval dense, `TOP_K=4`, local embeddings, 800/120 chunks, no dedupe, no
    boilerplate strip, exact search, 432 chunks and the 41 eval questions plus 30 bank questions drawn with seed 42. A real run under other settings stops before the
    first request and names each difference, and the check gives no verdict to a measurement made under other settings, on another index or on other questions.
17. **The planted answer does not stand out by how it is placed or worded.** Right answers as rare as it sit inside the complaint's window and under the document the
    complaint names; it is worded like right answers that state another, right figure; its day, hour and channel are drawn like everyone else's; and its figure is, in
    some drills, one the other document states. What is left is the figure itself and the document it cites, which is the check the drill is for.

## What the log can and cannot say

It can say which step took the time and how much of a model call was waiting; how many tokens a request used when the provider said; which
documents the answer cited and which it was shown; why it refused; which index and which model answered. It cannot say what a request would
have cost on another provider, whether an answer was right, or anything about a request that was not logged (the agent, race, eval and
diagnose runs). `tokens_known` is false, and the totals are lower bounds, when a provider reports no usage.

## Considered and deferred

| Idea | Why it was left, and what the log already holds toward it |
|---|---|
| OpenTelemetry and hosted tracers (LangSmith and others) | Each needs a collector or an account, and the lines already carry the shape: a request is a trace, a step is a span with a start and a duration, the model step carries the requested and served model and the input and output tokens. The OpenTelemetry GenAI conventions name these `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens`; check the current names before relying on this. An exporter would be a short function over the log. |
| Prompt caching (the provider reuses an identical prefix) | It happens on the provider's side and is not controlled from here; the model step records `cached_tokens` when the provider reports it, so a saving would show in the log without any code. The instructions are a stable prefix; the passages change per question. |
| Semantic or exact answer caching | Whether it pays depends on how often the same question repeats, which the log answers (`find_requests.py --distinct-answers` groups identical answers). The eval runner already has an exact-input cache for offline runs. Not built until the repeat rate says it is worth the staleness risk. |
| Model routing (for example through LiteLLM) | Needs two models and evidence that the cheaper one is good enough on some questions; the Week 6 eval is the instrument for that evidence. One model on a free tier. |
| Fallbacks and rate limits | `app/llm.py` already limits and retries, and the log shows what that costs (`wait_ms`, `attempts`). A second-model fallback is a routing decision and waits for it. |
| Fine-tuning | A last resort, and there is no training data. The failure-to-test tool is the first half of collecting some. |
| A data flywheel | The loop exists in small: a failure found in the log becomes a case that guards the next change. Automating the finding is the part not built. |
| Log retention and redaction | Logs grow until deleted and hold the full text of questions and passages. The folders are ignored by git; nothing deletes or redacts them. |

## The measured results

Not measured yet. The command that fills this section is `python scripts/measure_cost.py --label w11 --model <model> --bank 30 --seed 42` (look first with `--dry-run`), then `python scripts/check_cost_prediction.py w11`; the generated output goes in `findings.md`.

## Requirement to code, check by check

Written at the tag, with the function names and line numbers of that tag.

## Left as they are, and said here

- The first step of each kind in a process pays one-time costs (the embedding model, the keyword index in hybrid mode): `--skip-cold` leaves them out of the step table,
  but `--compare` has no such option, and the flag is per kind, so the first keyword search in hybrid mode is marked cold only if it is the first retrieval step.
- Cited and listed documents are matched by name; the error view says an error record keeps only the length and a hash of the question but there is no filter on them.
- A minute-precision `--until` excludes that minute, a reversed window is silently empty, and there is no `--caller` filter. The default of `cost_report.py` reads only the
  request log (not `errors.jsonl`).
- `app.tracing` now loads the OpenAI SDK through `app.observability`, so a tool that only reads logs pays for the import. A lock call that fails for a reason other than "held
  by another process" is treated as busy. A `KeyboardInterrupt` closes the spans but does not write an error record.
- Only the notice answers of the drill are checked against the corpus; its other topics are right by construction (their templates were written from the documents) and a test
  checks each phrase they rely on. The commitment can be brute-forced and the salt protects nothing that the log does not already give away: it is an honour system.
- The shape test of the drill compares keys and value types with a real line, not every number's distribution.
- P6 of the prediction gives no allowance for noise where P5 does: a wobbling citation on one conflict question fails the whole prediction (that is what the stop rule is for).
- A passage reduced to its headings by the strip is kept, so "nothing left, refuse without asking" (`context_all_repeated`) fires only for a chunk of nothing but repeats. The repeats are
  counted once per process and index: an index rebuilt by another process with the same number of chunks is not noticed until this one restarts.
- The failure tool proves a case against the correct answer you give it; whether the live model would give that answer is shown only by a live run.
- New log lines are written with LF; Weeks 3 to 10 wrote CRLF on Windows. Readers accept both. A `traces.jsonl.lock` file appears beside each log.
- `scripts/check_all.py` compiles every file in one command line, which can exceed Windows' limit in a very long checkout path.
- Several tests of Weeks 7 to 10 read settings from the environment (the price settings, `LLM_RPM`, `AGENT_MAX_STEPS`, `AGENT_MAX_CALLS_PER_TOOL`), so a value in `.env` or
  the shell can fail them. The Week 11 tests pin what they read; the older ones are not touched here.
- The bands in `prediction.md` were derived from the mean of the per-question saved shares the screen prints (17.9% on the eval questions, 27.2% on the bank draw), and
  P1 and P2 test the ratio of mean prompt tokens; the same screen prints the means in characters (3131 to 2617 and 2921 to 2148), which give somewhat different ratios.
  The registered bands contain the range from either, so no verdict depends on it, and the document is left as it was registered. Idea C's 9.8% is a mean over all
  71 questions, printed beside idea A's figures per kind.
- A line of a drill still differs from a real one in ways its shape test cannot see: the order of its keys (`refusal_cause` comes after `origin`), ids that are random
  hex digits and not the start of a version-4 UUID, a `config` that holds today's `top_k` and chunk sizes, and `meta.window.end`, which is an exclusive bound. None of
  them touches the planted request, which is built like every other.
- Every record the log tools read keeps its raw line, so reading a log holds about three times its size in memory. The per-step table of `cost_report.py` has no dollar
  column (dollars are per request there and per step in `find_requests.py --show`), and the report ignores the total, cached and reasoning tokens the app records, so its
  dollars are prompt plus completion tokens at the prices you state.
- `--cited` finds the documents an answer names in its own tags; when the model wrote no tag the app lists every retrieved document as the sources, and only
  `--retrieved-from` finds those requests (together with every other request that retrieved the document).
- Some outputs of the measurement are checked only through the larger tests: the layout of the summary table and the plan line, and the `dirty` flag of the code stamp.
  Some edges of the logging core are too: the served model of a step is the last call's, the times of a step are sums over its calls, and the default two-second lock wait.
- The offline retrieval guard of the failure tool skips when the local embedding model is not downloaded; `scripts/check_all.py --strict` refuses a skipped test.

- Characters are not tokens. The free screen reports characters; tokens follow them to a first approximation and the measurement reports tokens.
- The repeats are counted from the stored chunks, not the original documents, so a line in an overlap counts twice.
- Free-tier quota is per model and per day, so a measurement is one model on one day. The `before-2` arm bounds the noise inside that day; it does not
  say what another model or another day would do.
- The drill is an honour system: the commitment can be brute-forced and the code can be read. Its figures come from one corpus.
- `errors.jsonl` is written only for requests that reach the pipeline, so a request the API rejects before that (a malformed body) has no record.
- The request log is as private as the questions asked: the full passage text is in every line. Redaction and retention are not built.
