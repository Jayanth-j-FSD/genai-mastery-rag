"""One place for every chat-model call: client, rate limit, retries and usage counting.

The free Gemini tier only allows a few requests per minute per model, and it
sometimes answers "503 high demand". If every part of the app called the API on its own, each
would need its own waiting and retrying code. Instead they all call `chat()` here.

What `chat()` adds on top of the plain OpenAI client:
  1. A rolling one-minute limiter per model (LLM_RPM / JUDGE_RPM), so we wait instead of failing.
  2. Retries for the errors that are worth retrying (429 rate limit, 5xx, dropped connection),
     honouring the "retry in 51s" hint the API sends. A daily quota is NOT retried: waiting a
     minute cannot fix it, so it fails at once with a clear message.
  3. Counters for calls, tokens and seconds, so later weeks can report cost and speed
     (`usage_snapshot()` before a piece of work, `usage_since()` after it).
  4. An optional record of every call, kept per piece of work (`call_scope()`): the counters above are one
     process-wide total, so they cannot say which agent or which step spent what once work is nested or
     overlaps. A scope collects the calls made inside it and nothing else.

The client is created with max_retries=0 on purpose: the SDK's own hidden retries would spend
the per-minute allowance without us seeing it.
"""
import contextlib
import contextvars
import itertools
import re
import time
from collections import defaultdict, deque

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from app.config import settings

_client = None
_call_times = defaultdict(deque)       # model -> timestamps of calls in the last minute
_usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "api_seconds": 0.0, "wait_seconds": 0.0}
_last_model = {"name": None}           # the model the provider says answered the latest call
_scopes = contextvars.ContextVar("llm_call_scopes", default=())    # the open call scopes of this context, innermost last
_sequence = itertools.count(1)         # numbers the recorded calls in the order they finished, across every scope

_WINDOW_SECONDS = 60.0
_BACKOFF_SECONDS = (5, 10, 20, 40)     # for 5xx and connection errors when the API gives no hint


class QuotaExhausted(RuntimeError):
    """The provider says the DAILY quota is used up. Retrying within the day cannot help."""


def _get_client() -> OpenAI:
    """Create the client once. Honours OPENAI_BASE_URL, so Gemini works through the same SDK."""
    global _client
    if _client is None:
        key = settings.openai_api_key
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")
        _client = OpenAI(api_key=key, base_url=settings.openai_base_url or None, max_retries=0,
                         timeout=settings.llm_timeout_seconds)
    return _client


# ---------------------------------------------------------------------------- usage counters

def usage_snapshot() -> dict:
    """A copy of the counters now. Pass it to usage_since() later to get just that stretch of work."""
    return dict(_usage)


def usage_since(before: dict) -> dict:
    """Counters accumulated since `before` was taken."""
    now = usage_snapshot()
    delta = {key: now[key] - before.get(key, 0) for key in now}
    delta["api_seconds"] = round(delta["api_seconds"], 3)       # hide float noise in reports
    delta["wait_seconds"] = round(delta["wait_seconds"], 3)
    return delta


def reset_usage() -> None:
    for key in _usage:
        _usage[key] = 0.0 if isinstance(_usage[key], float) else 0


def reset_last_model() -> None:
    """Forget the last model name, so a caller can tell whether THIS piece of work made a model call."""
    _last_model["name"] = None


def message_of(response):
    """The first message of a chat response, or None when the provider returned no choices.

    A provider can answer with an empty list (a blocked reply, for example). Indexing choices[0]
    would turn that into a crash, so every reader goes through here.
    """
    choices = getattr(response, "choices", None) or []
    return choices[0].message if choices else None


def text_of(response) -> str:
    """The reply text, stripped; an empty string when there is no message or no content."""
    message = message_of(response)
    return ((getattr(message, "content", None) if message is not None else None) or "").strip()


def last_model():
    """The model name the provider reported on the latest successful call, or None.

    Aliases like "gemini-flash-latest" move over time, so a trace that only records the alias
    cannot be replayed later. The provider's own `model` field names what really ran.
    """
    return _last_model["name"]


# ---------------------------------------------------------------------------- per-scope call records

class CallScope:
    """The model calls made inside one `with call_scope(label)` block, one dict per call.

    A call is recorded in the INNERMOST open scope only, so an agent run nested inside a tool call of another
    agent is counted for itself and not for its parent. Each record: seq (the order calls finished in, across all
    scopes: a clock can tie, this cannot), started_at (seconds since the epoch, when chat() was entered), seconds (time inside the provider, every attempt), wait_seconds (rate-limit pauses and
    retry back-off), attempts, model (as requested), served (as the provider named it, None when the call
    failed), prompt_tokens, completion_tokens (0 when it failed), status ("ok" or "error") and error (the
    exception type that ended a failed call, else None). Three more numbers are there when the provider reports
    them, else None: total_tokens, cached_tokens (the part of the prompt served from a cache) and
    reasoning_tokens (hidden thinking it counted). A total that is not prompt plus completion is tokens the two
    counters miss. `extra` is whatever the caller wants kept with the scope (the team keeps the hand-off number).
    A scope opened inside another is listed in the outer one's `children`, so an outer scope can still total everything
    done under it (`walk()`, `totals(deep=True)`), while `calls` holds only its own.
    """

    def __init__(self, label="", **extra):
        self.label = label
        self.extra = extra
        self.calls = []
        self.children = []

    def walk(self):
        """(scope, call) for the calls of this scope and of every scope opened inside it, in the order the calls finished."""
        pairs = [(self, call) for call in self.calls]
        for child in self.children:
            pairs.extend(child.walk())
        return sorted(pairs, key=lambda pair: pair[1]["seq"])

    def totals(self, deep=False):
        """The same five keys as usage_snapshot(), summed over the calls recorded here, or over this scope and everything
        opened inside it with deep=True (failed calls add seconds only)."""
        every = [call for _scope, call in self.walk()] if deep else self.calls
        ok = [call for call in every if call["status"] == "ok"]
        return {"calls": len(ok), "prompt_tokens": sum(call["prompt_tokens"] for call in ok),
                "completion_tokens": sum(call["completion_tokens"] for call in ok),
                "api_seconds": round(sum(call["seconds"] for call in every), 3),
                "wait_seconds": round(sum(call["wait_seconds"] for call in every), 3)}


@contextlib.contextmanager
def call_scope(label="", **extra):
    """Record the model calls made inside the block: `with llm.call_scope("researcher") as scope: ...; scope.calls`.

    Scopes nest. They live in a ContextVar, so threads started with `contextvars.copy_context().run(...)` (which
    FastAPI's worker threads do for a request) record into the scope of the code that started them, and a thread
    started any other way starts with no scope and records nothing. Nothing changes for code that opens no scope.
    """
    scope = CallScope(label, **extra)
    open_scopes = _scopes.get()
    if open_scopes:
        open_scopes[-1].children.append(scope)
    token = _scopes.set(open_scopes + (scope,))
    try:
        yield scope
    finally:
        _scopes.reset(token)


def _record_call(began, seconds, paused, attempts, model, served=None, prompt_tokens=0, completion_tokens=0, error=None,
                 total_tokens=None, cached_tokens=None, reasoning_tokens=None):
    """Add one call record to the innermost open scope, if there is one."""
    scopes = _scopes.get()
    if scopes:
        scopes[-1].calls.append({"seq": next(_sequence), "started_at": began, "seconds": seconds, "wait_seconds": paused, "attempts": attempts,
                                 "model": model, "served": served, "prompt_tokens": prompt_tokens,
                                 "completion_tokens": completion_tokens,
                                 "status": "ok" if error is None else "error", "error": error,
                                 "total_tokens": total_tokens, "cached_tokens": cached_tokens, "reasoning_tokens": reasoning_tokens})


def _count(value):
    """A token count the provider reported, or None: anything that is not a plain whole number is not a count."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


# ---------------------------------------------------------------------------- rate limiting

def _wait_for_slot(model: str, rpm: int) -> float:
    """Block until another call to `model` fits in the per-minute allowance. rpm <= 0 means no limit.
    Returns the seconds spent waiting."""
    if rpm <= 0:
        return 0.0
    waited = 0.0
    window = _call_times[model]
    while True:
        now = time.monotonic()
        while window and now - window[0] >= _WINDOW_SECONDS:
            window.popleft()                      # forget calls older than a minute
        if len(window) < rpm:
            break
        pause = _WINDOW_SECONDS - (now - window[0]) + 0.05
        _usage["wait_seconds"] += pause
        waited += pause
        time.sleep(pause)
    window.append(time.monotonic())
    return waited


# ---------------------------------------------------------------------------- error reading

def _error_text(error: Exception) -> str:
    body = getattr(error, "body", None)
    return f"{error} {body}" if body else str(error)


def _retry_hint_seconds(error: Exception):
    """Seconds the API asked us to wait ("Please retry in 51.14s" or retryDelay '51s'), else None."""
    match = re.search(r"retry in ([0-9.]+)s", _error_text(error), re.IGNORECASE) or \
        re.search(r"retryDelay['\"]?\s*:\s*['\"]?([0-9.]+)s", _error_text(error))
    return float(match.group(1)) if match else None


def _is_daily_quota(error: Exception) -> bool:
    text = _error_text(error)
    return "PerDay" in text or "per day" in text.lower()


def _delay_for(error: Exception, attempt: int):
    """How long to wait before retrying, or None if this error should not be retried."""
    if isinstance(error, (APIConnectionError, APITimeoutError)):
        return _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
    if isinstance(error, APIStatusError):
        if error.status_code == 429:
            if _is_daily_quota(error):
                raise QuotaExhausted(
                    "The free daily quota for this model is used up. Try another model "
                    "(LLM_MODEL / JUDGE_MODEL) or wait until it resets."
                ) from error
            hint = _retry_hint_seconds(error)
            return (hint + 1.0) if hint is not None else 30.0
        if error.status_code >= 500:
            return _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
    return None                                  # 400, 401, 404 and friends: retrying will not fix them


# ---------------------------------------------------------------------------- the call

def chat(messages, model: str = "", rpm=None, **kwargs):
    """Call the chat model and return the SDK response (use `.choices[0].message`).

    model   defaults to LLM_MODEL. Pass settings.judge_model etc. for another model.
    rpm     per-minute limit for THIS model; defaults to LLM_RPM. 0 turns the limiter off.
    kwargs  anything chat.completions.create accepts: temperature, tools, tool_choice, ...
    """
    model = model or settings.llm_model
    rpm = settings.llm_rpm if rpm is None else rpm
    kwargs.setdefault("temperature", 0)
    attempts = max(1, settings.llm_max_retries + 1)
    # What this one call spent across all its attempts, for the call_scope record (the counters above are separate).
    began, provider_seconds, paused_seconds = time.time(), 0.0, 0.0

    for attempt in range(attempts):
        paused_seconds += _wait_for_slot(model, rpm)
        started = time.monotonic()
        try:
            response = _get_client().chat.completions.create(model=model, messages=messages, **kwargs)
        except Exception as error:               # decide below whether this one is worth retrying
            elapsed = time.monotonic() - started
            _usage["api_seconds"] += elapsed
            provider_seconds += elapsed
            try:
                delay = _delay_for(error, attempt)
            except QuotaExhausted as quota:      # the daily cap: no retry can help, so the call ends here
                _record_call(began, provider_seconds, paused_seconds, attempt + 1, model, error=type(quota).__name__)
                raise
            if delay is None or attempt == attempts - 1:
                _record_call(began, provider_seconds, paused_seconds, attempt + 1, model, error=type(error).__name__)
                raise
            _usage["wait_seconds"] += delay
            paused_seconds += delay
            time.sleep(delay)
            continue
        elapsed = time.monotonic() - started
        _usage["api_seconds"] += elapsed
        provider_seconds += elapsed
        _usage["calls"] += 1
        served = getattr(response, "model", None) or model
        _last_model["name"] = served
        counts = getattr(response, "usage", None)
        prompt_tokens = (getattr(counts, "prompt_tokens", 0) or 0) if counts is not None else 0
        completion_tokens = (getattr(counts, "completion_tokens", 0) or 0) if counts is not None else 0
        _usage["prompt_tokens"] += prompt_tokens
        _usage["completion_tokens"] += completion_tokens
        prompt_details = getattr(counts, "prompt_tokens_details", None)
        completion_details = getattr(counts, "completion_tokens_details", None)
        _record_call(began, provider_seconds, paused_seconds, attempt + 1, model, served, prompt_tokens, completion_tokens,
                     total_tokens=_count(getattr(counts, "total_tokens", None)),
                     cached_tokens=_count(getattr(prompt_details, "cached_tokens", None)),
                     reasoning_tokens=_count(getattr(completion_details, "reasoning_tokens", None)))
        return response
