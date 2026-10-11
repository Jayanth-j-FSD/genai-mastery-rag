"""Run the eval cases against the app and save what happened.

This is what `python scripts/run_evals.py` calls. For every case it retrieves
chunks, asks the answer model, applies the free rule checks, optionally asks the AI judge, and
records everything in one JSON file that the report and comparison scripts read.

Three design choices, each there to keep a before-and-after number honest:

  A private index per configuration. The run builds (once) a Chroma collection named after the
  settings that shape the index and the content of the documents, and points the app at it. Your
  main index is never touched, and "after" differs from "before" by exactly the setting you changed,
  not by whatever state your main index happened to be in.
  Caching by exact input. An answer or a verdict is reused only when the model, the prompt and every
  character of the input are identical. Re-running costs nothing for unchanged cases, which matters
  on a free tier, and a changed retrieval changes the key so it is never served a stale answer.
  Stop, save, resume. If the provider's daily quota runs out, the run saves what it finished and
  stops with a clear message. The cache means the next run picks up where this one ended.
"""
import contextlib
import hashlib
import json
import os
import re
from datetime import datetime

import openai

from app import llm
from app.config import BASE_DIR, Settings, settings
from app.rag import chunker, generator, keyword, loader, pipeline, retriever, store
from evals import checks, judge
from evals.cases import all_cases

RESULTS_DIR = os.path.join(BASE_DIR, "evals", "results")
CACHE_DIR = os.path.join(BASE_DIR, "evals", "cache")
INDEX_PREFIX = "eval_"


# ---------------------------------------------------------------------------- settings overrides

def parse_overrides(pairs):
    """["top_k=2", "retrieval_mode=hybrid"] -> {"top_k": 2, "retrieval_mode": "hybrid"}.

    The type of each value comes from the setting it replaces. An unknown name is an error, not a
    silently ignored typo: a mistyped override would otherwise run the "after" experiment unchanged.
    """
    overrides = {}
    for pair in pairs or []:
        key, separator, raw = pair.partition("=")
        key, raw = key.strip(), raw.strip()
        if not separator or key not in Settings.model_fields:       # not hasattr: methods such as copy() are not settings
            raise ValueError(f"--set expects name=value for an existing setting, got {pair!r}")
        current = getattr(settings, key)
        if isinstance(current, bool):
            if raw.lower() not in ("1", "0", "true", "false", "yes", "no", "on", "off"):
                raise ValueError(f"{key} is a yes/no setting, got {raw!r}")
            overrides[key] = raw.lower() in ("1", "true", "yes", "on")
        elif isinstance(current, int):
            overrides[key] = int(raw)
        elif isinstance(current, float):
            overrides[key] = float(raw)
        else:
            overrides[key] = raw
    return overrides


@contextlib.contextmanager
def overridden(overrides):
    """Apply setting overrides for the duration of a block, validating them like .env values.

    The overrides are checked on a copy first, and the VALIDATED values are the ones applied, so a value the
    validators tidy up (embed_provider=Local becomes local) is what the app really runs with. Nothing is
    changed unless every override is valid, and everything is restored when the block ends or fails.
    """
    unknown = [key for key in overrides if key not in Settings.model_fields]
    if unknown:
        raise ValueError(f"invalid override: not a setting: {unknown}")
    try:
        validated = Settings(_env_file=None, **{**settings.model_dump(), **overrides})      # runs the validators
    except Exception as exc:
        raise ValueError(f"invalid override: {exc}") from exc
    saved = {key: getattr(settings, key) for key in overrides}
    try:
        for key in overrides:
            setattr(settings, key, getattr(validated, key))
        yield
    finally:
        for key, value in saved.items():
            setattr(settings, key, value)


# ---------------------------------------------------------------------------- the private index

def _fingerprint(docs):
    digest = hashlib.sha256()
    for doc in sorted(docs, key=lambda d: d["source"]):
        digest.update(doc["source"].encode("utf-8"))
        digest.update(doc["text"].encode("utf-8"))
    return digest.hexdigest()


def index_key(docs):
    """Everything that decides what is in the index: the documents and every setting that shapes it."""
    shaping = {"embed_provider": settings.embed_provider, "embed_model": settings.embed_model,
               "chunk_size": settings.chunk_size, "chunk_overlap": settings.chunk_overlap,
               "dedupe_chunks": getattr(settings, "dedupe_chunks", False)}
    if getattr(settings, "boilerplate_min_repeats", 0):      # only when on, so every earlier index keeps its name
        shaping["boilerplate_min_repeats"] = settings.boilerplate_min_repeats
    return hashlib.sha256(json.dumps([shaping, _fingerprint(docs)], sort_keys=True).encode()).hexdigest()


def expected_chunk_count(docs):
    """How many chunks an ingest with the current settings should produce."""
    return len(pipeline.build_chunks(docs)) if hasattr(pipeline, "build_chunks") \
        else len(chunker.chunk_documents(docs, settings.chunk_size, settings.chunk_overlap))


@contextlib.contextmanager
def isolated_index():
    """Point the app at a collection built for this configuration, then put it back. Yields (name, count)."""
    docs = loader.load_documents(settings.corpus_dir)
    if not docs:
        raise RuntimeError(f"No readable documents in {settings.corpus_dir!r}.")
    name = INDEX_PREFIX + index_key(docs)[:12]
    wanted = expected_chunk_count(docs)
    original = settings.collection
    settings.collection = name
    keyword.invalidate()                      # the keyword cache is keyed by chunk count alone
    try:
        if store.count_chunks() != wanted:    # missing or half-built: (re)build it
            pipeline.ingest()
        yield name, wanted
    finally:
        settings.collection = original
        keyword.invalidate()


def clean_indexes():
    """Delete every private eval index. Returns how many were removed."""
    client = store._get_client()
    removed = 0
    for collection in client.list_collections():
        name = getattr(collection, "name", collection)
        if str(name).startswith(INDEX_PREFIX):
            client.delete_collection(name)
            removed += 1
    return removed


# ---------------------------------------------------------------------------- caching

class JsonCache:
    """A tiny file-backed dictionary. Written after every put, so an interrupted run loses nothing."""

    def __init__(self, path, enabled=True):
        self.path, self.enabled, self.hits, self.data = path, enabled, 0, {}
        if enabled and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    self.data = json.load(handle)
            except (OSError, json.JSONDecodeError):
                self.data = {}                # a damaged cache is just an empty one

    def get(self, key):
        value = self.data.get(key) if self.enabled else None
        if value is not None:
            self.hits += 1
        return value

    def put(self, key, value):
        if not self.enabled:
            return
        self.data[key] = value
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle, ensure_ascii=False)
        os.replace(temporary, self.path)


def _answer_key(question, chunks):
    parts = [settings.llm_model, generator.SYSTEM_PROMPT, question, [(c["source"], c["text"]) for c in chunks]]
    if settings.min_relevance > 0:
        # With a relevance floor the generator may refuse WITHOUT calling the model, so the floor and the best
        # score decide the answer. They join the key only when the floor is on, so earlier keys stay valid.
        parts.append([settings.min_relevance, max((c.get("score") or 0 for c in chunks), default=None)])
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode("utf-8")).hexdigest()


def answer_one(question, chunks, cache):
    """The app's answer for these exact chunks. Returns (reply dict, was_cached)."""
    key = _answer_key(question, chunks)
    cached = cache.get(key)
    if cached is not None:
        return cached, True
    llm.reset_last_model()                    # an answer given without a model call must not claim the last call's model
    answer, sources, grounded = generator.generate_answer(question, chunks)
    reply = {"answer": answer, "grounded": grounded, "sources": [s.document for s in sources],
             "model_served": llm.last_model()}
    cache.put(key, reply)
    return reply, False


def judge_one(case, result, cache):
    """The judge's verdict for this answer. Returns (verdict dict, was_cached)."""
    model = judge.judge_model()
    key = judge.cache_key(model, case["question"], result["retrieved"], result["answer"], case["reference"])
    cached = cache.get(key)
    if cached is not None:
        return cached, True
    verdict = judge.judge_answer(case["question"], result["retrieved"], result["answer"], case["reference"], model)
    if verdict["verdict"] != "error":         # never cache an unreadable reply: ask again next time
        cache.put(key, verdict)
    return verdict, False


# ---------------------------------------------------------------------------- the run

def safe_label(label):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", label.strip()) or "run"


def results_path(label, directory=None):
    return os.path.join(directory or RESULTS_DIR, safe_label(label) + ".json")


def run_cases(cases, label="latest", with_judge=True, use_cache=True, overrides=None, say=print):
    """Run every case and return the results dict. Stops early, saved as incomplete, if a quota runs out."""
    answers = JsonCache(os.path.join(CACHE_DIR, "answers.json"), use_cache)
    verdicts = JsonCache(os.path.join(CACHE_DIR, "judge.json"), use_cache)
    started = datetime.now().isoformat(timespec="seconds")
    usage_start = llm.usage_snapshot()
    results = {"meta": {}, "cases": []}
    stopped, served = None, None

    with isolated_index() as (collection, chunk_count):
        for case in cases:
            usage_before = llm.usage_snapshot()
            try:
                chunks = retriever.retrieve_for_mode(case["question"], settings.top_k, settings.retrieval_mode)
                reply, answer_cached = answer_one(case["question"], chunks, answers)
                served = served or reply.get("model_served")
                result = {**reply, "retrieved": [
                    {"chunk_id": c.get("chunk_id", ""), "source": c["source"], "score": c.get("score"), "text": c["text"]}
                    for c in chunks]}
                rule_checks, passed, warnings = checks.check_case(case, result)
                judged = judge_cached = None
                if with_judge:
                    judged, judge_cached = judge_one(case, result, verdicts)
            except (llm.QuotaExhausted, openai.OpenAIError) as exc:
                # A daily quota, or a provider failure that survived the retries: keep what finished and stop.
                stopped = str(exc) if isinstance(exc, llm.QuotaExhausted) else f"the provider failed ({type(exc).__name__}): {exc}"
                say(f"\nSTOPPED at case {case['id']!r}: {stopped}\nSaved what finished; run again later to resume (cached calls are free).")
                break
            entry = {"id": case["id"], "problem_type": case["problem_type"], "origin": case.get("origin", ""),
                     "question": case["question"], "reference": case["reference"],
                     "expected_sources": case["expected_sources"], "should_refuse": case["should_refuse"],
                     "answer": result["answer"], "grounded": result["grounded"], "sources": result["sources"],
                     "retrieved": result["retrieved"], "checks": rule_checks, "passed": passed,
                     "warnings": warnings, "judge": judged,
                     "cached": {"answer": answer_cached, "judge": judge_cached},
                     "usage": llm.usage_since(usage_before)}
            results["cases"].append(entry)
            flag = "ok  " if passed and (judged is None or judged["verdict"] == "pass") else "FAIL"
            say(f"[{flag}] {case['id']:<32} {case['problem_type']}")

    results["meta"] = {
        "label": label, "started": started, "finished": datetime.now().isoformat(timespec="seconds"),
        "complete": stopped is None, "stopped_because": stopped,
        "n_cases": len(results["cases"]), "n_requested": len(cases),
        "collection": collection, "chunk_count": chunk_count,
        "models": {"answer": settings.llm_model, "judge": judge.judge_model() if with_judge else None,
                   "answer_served": served},
        "settings": {"retrieval_mode": settings.retrieval_mode, "dense_search": settings.dense_search,
                     "top_k": settings.top_k, "chunk_size": settings.chunk_size,
                     "chunk_overlap": settings.chunk_overlap, "embed_provider": settings.embed_provider,
                     "min_relevance": settings.min_relevance,
                     "dedupe_chunks": getattr(settings, "dedupe_chunks", False),
                     "boilerplate_min_repeats": getattr(settings, "boilerplate_min_repeats", 0)},
        "overrides": overrides or {},
        "cache_hits": {"answers": answers.hits, "judge": verdicts.hits},
        "usage": llm.usage_since(usage_start),
    }
    return results


def save_results(results, path=None):
    """Write a run to its file. A run that stopped early never replaces a complete run with the same label:
    it is written beside it as `<label>.incomplete.json`, so a quota that runs out cannot destroy a good result.
    """
    path = path or results_path(results["meta"]["label"])
    if not results["meta"].get("complete", True) and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as handle:
                existing_is_complete = bool(json.load(handle).get("meta", {}).get("complete", False))
        except (OSError, json.JSONDecodeError):
            existing_is_complete = False
        if existing_is_complete:
            path = path[: -len(".json")] + ".incomplete.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(results, handle, ensure_ascii=False, indent=1)
        os.replace(temporary, path)                # a write cut short never leaves half a file where a good one was
    except BaseException:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    return path


def load_results(path_or_label):
    """Load a saved run by file path or by label."""
    path = path_or_label if os.path.exists(path_or_label) else results_path(path_or_label)
    if not os.path.exists(path):
        raise FileNotFoundError(f"No saved run at {path}")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def select_cases(only=None, types=None, limit=None, regressions_path=None):
    """The cases to run, optionally narrowed by id, by problem type, or to the first N."""
    cases = all_cases(regressions_path)
    if only:
        wanted = set(only)
        unknown = wanted - {c["id"] for c in cases}
        if unknown:
            raise ValueError(f"unknown case id(s): {sorted(unknown)}")
        cases = [c for c in cases if c["id"] in wanted]
    if types:
        cases = [c for c in cases if c["problem_type"] in set(types)]
    return cases[:limit] if limit else cases
