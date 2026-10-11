"""What one request did, step by step: the request, its spans, and what each cost (Week 11).

A TRACE is the story of one request. It is made of SPANS, one per step the request took (turning the
question into numbers, searching, asking the model), each with how long it took and, for the model, how many tokens it
used. With one number for the whole request you can only say "it was slow"; with spans you can say which step.

Three rules this module keeps, because a log that gets them wrong is worse than none:

  1. Logging never breaks answering. Every function here that runs while a request is being answered catches its own
     failure, says so once, and carries on, so a bug in the log cannot turn a paid answer into an error.
  2. A span is one step, not a group of steps. Spans do not overlap, so their durations add up to at most the whole
     request, and a request's tokens are the sum of its model spans.
  3. The model span keeps the waiting apart. On a free tier most of a model call's wall time can be the app sleeping to
     stay under a rate limit or backing off after an error. `duration_ms` is wall time, `provider_ms` is time inside the
     provider, `wait_ms` is the waiting, so a slow request can be told from a request that was merely queued.

Tokens are logged as facts. Dollars are not: a price is an assumption (app/pricing.py), so `cost_usd` is filled only when
a price is set, together with the prices used, and the report scripts compute dollars again from the tokens with prices
you state. This module does no file input or output: app/tracing.py writes the lines.
"""
import contextlib
import contextvars
import hashlib
import threading
import time
import uuid
from datetime import datetime, timezone

from app import llm, pricing
from app.config import settings

_current = contextvars.ContextVar("observability_request", default=None)         # the request being answered, if any
_last_id = contextvars.ContextVar("observability_last_request_id", default=None)  # the id of the latest request, kept after it ends
_channel = contextvars.ContextVar("observability_channel", default=("unknown", None))
_seen_kinds, _seen_lock, _warned = set(), threading.Lock(), set()


def _warn_once(where, exc):
    """Say that the log failed, once per place per process, and let the answer go on."""
    if where not in _warned:
        _warned.add(where)
        print(f"  ! request log failed in {where} (ignored): {type(exc).__name__}")


def guarded(where, function, *args, default=None, **kwargs):
    """Run a piece of logging; if it fails, warn once and return `default`. Nothing that logs may raise into an answer."""
    try:
        return function(*args, **kwargs)
    except Exception as exc:                          # logging must never break answering
        _warn_once(where, exc)
        return default


def sha12(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12]


def _iso_ms(moment):
    return moment.isoformat(timespec="milliseconds")


def new_request_id():
    """A 16-hex-digit id. Its first 8 are the trace id the older log lines carry."""
    return uuid.uuid4().hex[:16]


# ---------------------------------------------------------------------------- who is asking

@contextlib.contextmanager
def channel(name, caller=None):
    """Say how the request arrived (api, cli, batch) and, optionally, who sent it, for the requests made inside the block."""
    token = _channel.set((name, caller))
    try:
        yield
    finally:
        _channel.reset(token)


def last_request_id():
    """The id of the latest request this context answered (or failed), or None. It is NOT cleared when the request ends:
    the code that handles an error needs it afterwards."""
    return _last_id.get()


def forget_last_request():
    _last_id.set(None)


def current():
    """The request being answered right now, or None."""
    return _current.get()


# ---------------------------------------------------------------------------- the request and its spans

class RequestLog:
    """One request's spans and notes. Built by begin_request(); read by app/tracing.py when the line is written."""

    def __init__(self, request_id, clock, channel_name, caller):
        self.request_id, self.trace_id = request_id, request_id[:8]
        self.clock, self.t0 = clock, clock()
        self.started_at = _iso_ms(datetime.now().astimezone())
        self.ts_utc = _iso_ms(datetime.now(timezone.utc))
        self.channel, self.caller = channel_name, caller
        self.spans, self.notes = [], {}
        self._next_id = 1
        self._lock = threading.Lock()

    def open_span(self, name, kind, attrs):
        with self._lock:
            span_id, self._next_id = self._next_id, self._next_id + 1
        with _seen_lock:
            cold = kind not in _seen_kinds
            _seen_kinds.add(kind)
        return {"span_id": span_id, "name": name, "kind": kind, "start": self.clock(), "cold": cold, "attrs": dict(attrs)}

    def close_span(self, handle, error=None):
        end = self.clock()
        span = {"span_id": handle["span_id"], "name": handle["name"], "kind": handle["kind"],
                "start_ms": round((handle["start"] - self.t0) * 1000, 3), "duration_ms": round((end - handle["start"]) * 1000, 3),
                "status": "error" if error is not None else "ok", "error": type(error).__name__ if error is not None else None,
                "cold": handle["cold"]}
        span.update(handle["attrs"])
        with self._lock:
            self.spans.append(span)
        return span

    def total_ms(self):
        return round((self.clock() - self.t0) * 1000, 3)

    def model_spans(self):
        return [span for span in self.spans if span["kind"] == "model"]

    def usage(self):
        """The request's tokens: the sum of its model spans. `tokens_known` is False when any model span has no usage from the
        provider, because then the sums are lower bounds, not the truth."""
        spans = self.model_spans()
        return {"model_calls": len(spans), "prompt_tokens": sum(s.get("prompt_tokens") or 0 for s in spans),
                "completion_tokens": sum(s.get("completion_tokens") or 0 for s in spans),
                "tokens_known": all(s.get("tokens_known") for s in spans) if spans else True,
                "provider_ms": round(sum(s.get("provider_ms") or 0 for s in spans), 3),
                "wait_ms": round(sum(s.get("wait_ms") or 0 for s in spans), 3)}


@contextlib.contextmanager
def begin_request(clock=time.perf_counter, request_id=None):
    """Open a request: spans and notes made inside the block belong to it. It always closes, and the id stays readable
    (last_request_id) afterwards, so an error handler can name the request that failed."""
    name, caller = _channel.get()
    request = guarded("begin_request", RequestLog, request_id or new_request_id(), clock, name, caller)
    if request is None:                              # the log itself broke: answer without one
        yield None
        return
    token = _current.set(request)
    try:
        yield request
    finally:
        _current.reset(token)
        _last_id.set(request.request_id)


@contextlib.contextmanager
def span(name, kind, **attrs):
    """One step of the current request, timed. A no-op outside a request. Failing logging code never changes what the block does."""
    request = _current.get()
    handle = guarded("span", request.open_span, name, kind, attrs) if request is not None else None
    if handle is None:
        yield None
        return
    try:
        yield handle
    except BaseException as exc:
        guarded("span", request.close_span, handle, exc)
        raise
    else:
        guarded("span", request.close_span, handle)


@contextlib.contextmanager
def model_span(name, requested_model=None, **attrs):
    """A model call as a span: wall time, and from the call's own record the time inside the provider, the time spent waiting
    (rate limit and retry back-off), the tries, the tokens the provider reported, the model that answered, and the cost if
    a price is set. A call that failed keeps its span, with the error type. A no-op outside a request."""
    request = _current.get()
    handle = guarded("model_span", request.open_span, name, "model", attrs) if request is not None else None
    if handle is None:
        yield None
        return
    handle["attrs"]["model_requested"] = requested_model or settings.llm_model
    with llm.call_scope(name) as scope:
        failure = None
        try:
            yield handle
        except BaseException as exc:
            failure = exc
            raise
        finally:
            guarded("model_span", _fill_model_attrs, handle, scope)
            guarded("model_span", request.close_span, handle, failure)


def _sum_if_all_known(values):
    """The total of figures the provider reported, or None when any call did not report one (a lower bound is not a total)."""
    return None if any(value is None for value in values) else sum(values)


def _fill_model_attrs(handle, scope):
    """Copy what the recorder saw of the calls made inside the span onto it. One call is the normal case; with several the
    times and tokens are added up, and a token figure is known only when every call reported it."""
    calls, attrs = scope.calls, handle["attrs"]
    if not calls:                                     # the call never reached the recorder (it was replaced, or failed before)
        attrs.update(provider_ms=None, wait_ms=None, attempts=0, model_served=None, tokens_known=False,
                     prompt_tokens=None, completion_tokens=None, cost_usd=None)
        return
    known = all(call.get("usage_reported") for call in calls)
    prompt_tokens, completion_tokens = sum(call["prompt_tokens"] for call in calls), sum(call["completion_tokens"] for call in calls)
    attrs.update(provider_ms=round(sum(call["seconds"] for call in calls) * 1000, 3),
                 wait_ms=round(sum(call["wait_seconds"] for call in calls) * 1000, 3),
                 attempts=sum(call["attempts"] for call in calls), model_served=calls[-1].get("served"), tokens_known=known,
                 prompt_tokens=prompt_tokens if known else None, completion_tokens=completion_tokens if known else None,
                 total_tokens=_sum_if_all_known([call.get("total_tokens") for call in calls]),
                 cached_tokens=_sum_if_all_known([call.get("cached_tokens") for call in calls]),
                 reasoning_tokens=_sum_if_all_known([call.get("reasoning_tokens") for call in calls]))
    attrs.update(cost_fields(prompt_tokens, completion_tokens) if known else {"cost_usd": None})


def cost_fields(prompt_tokens, completion_tokens):
    """cost_usd only when a price is set (None otherwise: unknown is not free), with the prices that produced it."""
    cost = pricing.cost_of(prompt_tokens, completion_tokens)
    if cost is None:
        return {"cost_usd": None}
    input_per_m, output_per_m = pricing.current_prices()
    return {"cost_usd": round(cost, 8), "prices": {"input_per_million": input_per_m, "output_per_million": output_per_m,
                                                  "note": pricing.ASSUMPTION}}


# ---------------------------------------------------------------------------- notes and the finished record

def note(**fields):
    """Add facts to the current request (a refusal cause, the sources the answer cited). A no-op outside a request."""
    request = _current.get()
    if request is not None:
        guarded("note", lambda: request.notes.update(fields))     # the lambda keeps even a broken notes dict inside the guard


def record_extras(request, **final):
    """The new, optional keys a log line gets on top of the older ones: the id, times, spans, tokens and what was noted."""
    extras = {"request_id": request.request_id, "started_at": request.started_at, "ts_utc": request.ts_utc, "channel": request.channel,
              "total_ms": request.total_ms(), "spans": list(request.spans), "usage": request.usage()}
    if request.caller:
        extras["caller"] = request.caller
    extras.update(request.notes)
    extras.update(final)
    return extras


def snapshot(request):
    """What an error record keeps of a request that failed: its id, when, how it arrived and the spans it finished. No text."""
    return {"request_id": request.request_id, "started_at": request.started_at, "ts_utc": request.ts_utc, "channel": request.channel,
            "total_ms": request.total_ms(), "spans": [{key: span.get(key) for key in ("span_id", "name", "kind", "start_ms", "duration_ms", "status", "error")}
                                                      for span in request.spans]}
