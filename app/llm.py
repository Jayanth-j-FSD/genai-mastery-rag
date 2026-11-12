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

The client is created with max_retries=0 on purpose: the SDK's own hidden retries would spend
the per-minute allowance without us seeing it.
"""
import re
import time
from collections import defaultdict, deque

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from app.config import settings

_client = None
_call_times = defaultdict(deque)       # model -> timestamps of calls in the last minute
_usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "api_seconds": 0.0, "wait_seconds": 0.0}
_last_model = {"name": None}           # the model the provider says answered the latest call

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


# ---------------------------------------------------------------------------- rate limiting

def _wait_for_slot(model: str, rpm: int) -> None:
    """Block until another call to `model` fits in the per-minute allowance. rpm <= 0 means no limit."""
    if rpm <= 0:
        return
    window = _call_times[model]
    while True:
        now = time.monotonic()
        while window and now - window[0] >= _WINDOW_SECONDS:
            window.popleft()                      # forget calls older than a minute
        if len(window) < rpm:
            break
        pause = _WINDOW_SECONDS - (now - window[0]) + 0.05
        _usage["wait_seconds"] += pause
        time.sleep(pause)
    window.append(time.monotonic())


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

    for attempt in range(attempts):
        _wait_for_slot(model, rpm)
        started = time.monotonic()
        try:
            response = _get_client().chat.completions.create(model=model, messages=messages, **kwargs)
        except Exception as error:               # decide below whether this one is worth retrying
            _usage["api_seconds"] += time.monotonic() - started
            delay = _delay_for(error, attempt)
            if delay is None or attempt == attempts - 1:
                raise
            _usage["wait_seconds"] += delay
            time.sleep(delay)
            continue
        _usage["api_seconds"] += time.monotonic() - started
        _usage["calls"] += 1
        _last_model["name"] = getattr(response, "model", None) or model
        counts = getattr(response, "usage", None)
        if counts is not None:
            _usage["prompt_tokens"] += getattr(counts, "prompt_tokens", 0) or 0
            _usage["completion_tokens"] += getattr(counts, "completion_tokens", 0) or 0
        return response
