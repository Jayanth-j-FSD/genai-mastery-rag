"""The support drill's population: a synthetic request log with one wrong answer planted in it (Week 11).

A support drill is practice for the day someone says "the assistant gave a customer a wrong answer last week" and you
have a log and nothing else. This builds the log. It writes about three thousand requests spread over four weeks, shaped exactly
like the ones the real app logs (the same keys, the same steps, the same kinds of numbers), with questions and answers taken from
the documents in data/corpus. Among the notice-period answers, which are many and mostly differ only by company and status, exactly
ONE states a figure that is in none of the documents. The complaint you are given is vague, like a real one: a topic, a rough time
window and which document the answer cited, no number. Finding the request is your work; this file knows where it is and does not
say.

Three things make it a fair drill and not a trick:
  The wrongness rule is checkable by a machine. An answer to a notice question is wrong when it states a number of calendar days that
  the document(s) it cites do not state in a line about notice. The allowed figures are READ from the corpus, so if the corpus changes
  the rule changes with it, and the generator refuses to run if a figure its decoys state is no longer in the corpus.
  The decoys are right. Notice answers differ (30 or 7 days at Acme, 60 or 30 in the handbook, an answer that names both documents
  because they disagree), so "the odd one out" is not enough: you have to check a figure against the document.
  Every record says it is synthetic ("synthetic": true, "origin": "drill-kit", the model "synthetic-model"), so a drill log can never
  be mistaken for real traffic by a script or by a person.

The drill keeps a commitment, not a secret: sha256 of a random salt, the planted request's id and the hash of the log. A checker can
tell whether a guess is the planted one without the id being written anywhere, and nobody can quietly change the log afterwards.
Anyone determined can still brute-force it, which is why it is an honour system: the point is the practice.
"""
import hashlib
import json
import os
import random
import re
from datetime import datetime, timedelta, timezone

from app import tracing
from app.config import BASE_DIR, settings
from app.rag import chunker, generator, loader

SYNTHETIC_MODEL = "synthetic-model"
DRILL_DIR = os.path.join(BASE_DIR, "data", "drill")
VERSION = 1

ACME, HANDBOOK = "Acme-Employment-Terms-2026.md", "Synthetic_HR_Policy_RAG_Test_Dataset.md"
ACME_LEAVE, REMOTE, EXPENSES = "Acme-Leave-Policy-2026.md", "Northstar-Remote-Work-Policy-2026.md", "expenses.md"
SECURITY, SUPPORT, BENEFITS = "security-policy.md", "support-faq.md", "benefits.md"

# Figures a wrong answer might invent. One is picked at generation, and only from those the corpus does not contain as a whole word.
PLANT_CANDIDATES = (14, 15, 21, 28, 35, 40, 45, 50, 75, 90, 120)
_DAYS = re.compile(r"(?<!\d)(\d+)\s+calendar\s+days?", re.IGNORECASE)

# (name, weight, [question phrasings], [(answer template, [cited documents], phrase that must be in the first cited document, facts it states)]).
# A template's {figure} slots are filled from `facts`, which are checked against the corpus at generation, so a decoy cannot be wrong.
NOTICE = "notice"
TOPICS = [
    (NOTICE, 8.0, ["How much notice must a permanent employee give before resigning?", "What is the notice period if I resign?", "How long is the resignation notice period?",
                   "I want to quit, how many days of notice do I owe?", "What notice do I have to serve when I resign?"], [
        ("A permanent employee must give {30} calendar days of written notice before resigning. [source: " + ACME + "]", [ACME], "30 calendar days of written notice", {ACME: [30]}),
        ("A permanent employee must give {30} calendar days of written notice before resigning. [source: " + ACME + "]", [ACME], "30 calendar days of written notice", {ACME: [30]}),
        ("An employee still within the probationary period must give {7} calendar days of written notice. [source: " + ACME + "]", [ACME], "7 calendar days of written notice", {ACME: [7]}),
        ("The standard notice period is {60} calendar days for confirmed employees. [source: " + HANDBOOK + "]", [HANDBOOK], "60 calendar days", {HANDBOOK: [60]}),
        ("During probation the notice period is {30} calendar days. [source: " + HANDBOOK + "]", [HANDBOOK], "30 calendar days", {HANDBOOK: [30]}),
        ("The documents disagree: the Acme employment terms say {30} calendar days for permanent employees, while the handbook says {60} calendar days for confirmed "
         "employees. [source: " + ACME + ", " + HANDBOOK + "]", [ACME, HANDBOOK], "30 calendar days of written notice", {ACME: [30], HANDBOOK: [60]}),
        ("For a company-initiated termination without cause, Acme provides {30} calendar days of notice or pay in lieu of notice. [source: " + ACME + "]", [ACME],
         "30 calendar days of notice or pay in lieu", {ACME: [30]}),
    ]),
    ("annual-leave", 9.0, ["How many days of annual leave do I get?", "What is my annual leave entitlement?", "How much paid leave do I have each year?"], [
        ("Acme employees receive 18 days of annual leave a year. [source: " + ACME_LEAVE + "]", [ACME_LEAVE], "18 days", {}),
        ("The documents disagree: the Acme leave policy gives 18 days a year, while the handbook and benefits.md say 24. [source: " + ACME_LEAVE + ", " + BENEFITS + "]",
         [ACME_LEAVE, BENEFITS], "18 days", {}),
    ]),
    ("sick-leave", 6.0, ["How many sick days do I get?", "How many paid sick leave days are there?"], [
        ("There are 12 paid sick leave days a year. [source: " + ACME_LEAVE + "]", [ACME_LEAVE], "12", {})]),
    ("carry-forward", 5.0, ["How many leave days can I carry forward?", "Can I carry over unused leave?"], [
        ("Up to 10 unused days can be carried forward; the excess expires on 31 March unless People Operations approves otherwise in writing. [source: " + ACME_LEAVE + "]",
         [ACME_LEAVE], "10", {})]),
    ("parental-leave", 4.0, ["How long is paid parental leave?", "How many weeks of parental leave do I get?"], [
        ("Paid parental leave is 16 weeks. [source: " + ACME_LEAVE + "]", [ACME_LEAVE], "16 weeks", {})]),
    ("remote-work", 9.0, ["How many days a week can I work from home?", "Am I allowed to work remotely?", "What are the remote work rules?"], [
        ("Remote work is allowed up to three days a week after 60 days of service, with core hours from 10:00 to 16:00 local time. [source: " + REMOTE + "]", [REMOTE], "three days", {})]),
    ("internet-claim", 4.0, ["How much internet can I claim?", "What is the home internet allowance?"], [
        ("Up to 50 USD a month with an itemised receipt, submitted by the 10th of the following month. [source: " + REMOTE + "]", [REMOTE], "50 USD", {})]),
    ("meals", 6.0, ["What is the meal allowance?", "How much can I spend on meals when I travel?"], [
        ("Meals are reimbursed up to $40 a day. [source: " + EXPENSES + "]", [EXPENSES], "$40", {})]),
    ("expense-deadline", 5.0, ["How long do I have to submit an expense?", "What is the receipt window for expenses?"], [
        ("Submit the expense within 30 days of purchase, with a receipt. [source: " + EXPENSES + "]", [EXPENSES], "30 days", {})]),
    ("security-incident", 6.0, ["Who do I tell about a suspected security incident?", "I think my laptop was hacked, what do I do?"], [
        ("Report a suspected security incident to security@northwind.example within 1 hour. [source: " + SECURITY + "]", [SECURITY], "1 hour", {})]),
    ("password-reset", 7.0, ["How long is the password reset link valid?", "My password reset link does not work."], [
        ("The password reset link is valid for 30 minutes. [source: " + SUPPORT + "]", [SUPPORT], "30 min", {})]),
    ("error-4032", 6.0, ["What does ERR-4032 mean?", "I get ERR-4032 when I connect a source."], [
        ("ERR-4032 means the source connection timed out. Retry after 60 seconds and check Settings > Connections. [source: " + SUPPORT + "]", [SUPPORT], "ERR-4032", {})]),
    ("pension", 4.0, ["When does the pension match start?", "What is the pension match?"], [
        ("The pension match is 5% and starts after 3 months of employment. [source: " + BENEFITS + "]", [BENEFITS], "pension", {})]),
]
UNANSWERABLE = ["What is the annual bonus percentage?", "What is the dress code?", "What is the CTO's phone number?", "What is our Azure subscription ID?",
                "How much is the company car allowance?"]
REFUSAL_WEIGHT = 8.0


# ---------------------------------------------------------------------------- the corpus facts

def notice_figures_by_document(corpus_dir):
    """{document: the whole numbers of calendar days it states in lines that mention notice}. This is the wrongness rule's source of truth."""
    figures = {}
    for doc in loader.load_documents(corpus_dir):
        found = set()
        for line in doc["text"].splitlines():
            if "notice" in line.lower():
                found |= {int(number) for number in _DAYS.findall(line)}
        figures[doc["source"]] = found
    return figures


def _whole_word_in(corpus_dir, number):
    pattern = re.compile(r"(?<![\w.])" + str(number) + r"(?![\w])")
    return any(pattern.search(doc["text"]) for doc in loader.load_documents(corpus_dir))


def violations(records, corpus_dir):
    """The requests whose notice answer states a number of calendar days that the documents it cites do not state about notice.
    Written separately from the generator, from the log lines alone, so it can catch the generator being wrong."""
    allowed = notice_figures_by_document(corpus_dir)
    wrong = []
    for record in records:
        if NOTICE not in (record.get("question") or "").lower():
            continue
        figures = {int(number) for number in _DAYS.findall(record.get("answer") or "")}
        stated_by = set().union(*[allowed.get(name, set()) for name in record.get("sources") or []]) if record.get("sources") else set()
        if figures and not figures <= stated_by:
            wrong.append(record)
    return wrong


def check_facts(corpus_dir):
    """Refuse to build a drill whose decoys state something the corpus no longer says."""
    allowed = notice_figures_by_document(corpus_dir)
    for name, _weight, _questions, variants in TOPICS:
        if name != NOTICE:
            continue
        for _template, _cited, _phrase, facts in variants:
            for document, figures in facts.items():
                missing = [figure for figure in figures if figure not in allowed.get(document, set())]
                if missing:
                    raise RuntimeError(f"the drill's notice answers say {missing} calendar days for {document}, but that document no longer says so; "
                                       "update the templates in evals/drill.py before building a drill")


# ---------------------------------------------------------------------------- building the log

def _sha12(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _corpus_fingerprint(corpus_dir):
    digest = hashlib.sha256()
    for doc in sorted(loader.load_documents(corpus_dir), key=lambda d: d["source"]):
        digest.update(doc["source"].encode("utf-8") + doc["text"].encode("utf-8"))
    return digest.hexdigest()[:12]


class _Corpus:
    """The corpus cut into the same chunks the app indexes, so a retrieved passage in the log is a real passage."""

    def __init__(self, corpus_dir):
        self.chunks = chunker.chunk_documents(loader.load_documents(corpus_dir), settings.chunk_size, settings.chunk_overlap)
        self.fillers = [c for c in self.chunks if c["source"] == HANDBOOK]                # what crowds the real passage out in the real app

    def holding(self, document, phrase, rng):
        matching = [c for c in self.chunks if c["source"] == document and phrase.lower() in c["text"].lower()]
        return rng.choice(matching or [c for c in self.chunks if c["source"] == document] or self.chunks)

    def retrieved(self, document, phrase, rng, top_k=4, has_answer=True):
        """Four passages as dense retrieval returns them: the one with the answer (unless the question has none) and handbook passages
        that crowd in, best score first."""
        chosen = [self.holding(document, phrase, rng)] if has_answer else []
        taken = {c["chunk_id"] for c in chosen}
        chosen += rng.sample([c for c in self.fillers if c["chunk_id"] not in taken], top_k - len(chosen))
        scores = [round(rng.uniform(0.42, 0.72), 4)] if has_answer else []
        scores += sorted((round(rng.uniform(0.16, 0.24), 4) for _ in range(top_k - len(scores))), reverse=True)
        return [{"source": chunk["source"], "score": score, "retrievers": ["dense"], "dense_rank": rank, "keyword_rank": None, "keyword_score": None,
                 "rrf_score": None, "text": chunk["text"]} for rank, (chunk, score) in enumerate(zip(chosen, scores), start=1)]


def _spans(rng, retrieved, prompt_tokens, completion_tokens, cold):
    """The steps of one request, with the key set of the real ones and numbers of a believable size."""
    embed = round(rng.uniform(3, 14) * (40 if cold else 1), 3)
    search = round(rng.uniform(6, 48), 3)
    provider = round(rng.uniform(550, 1400) + 22 * completion_tokens * rng.uniform(0.8, 1.4), 3)
    roll = rng.random()
    wait = 0.0 if roll < 0.7 else round(rng.uniform(150, 3000), 3) if roll < 0.95 else round(rng.uniform(20000, 62000), 3)
    attempts = 2 if wait > 20000 else 1
    start = round(rng.uniform(0.4, 1.5), 3)
    spans = [{"span_id": 1, "name": "embed_query", "kind": "embed", "start_ms": start, "duration_ms": embed, "status": "ok", "error": None, "cold": cold,
              "provider": "local", "cost_usd": 0.0, "cost_basis": "local"},
             {"span_id": 2, "name": "search", "kind": "retrieve", "start_ms": round(start + embed + 0.05, 3), "duration_ms": search, "status": "ok", "error": None,
              "cold": cold, "mode": "dense", "top_k": len(retrieved)}]
    model_start = round(spans[1]["start_ms"] + search + 0.05, 3)
    spans.append({"span_id": 3, "name": "generate", "kind": "model", "start_ms": model_start, "duration_ms": round(provider + wait, 3), "status": "ok", "error": None,
                  "cold": cold, "model_requested": SYNTHETIC_MODEL, "provider_ms": provider, "wait_ms": wait, "attempts": attempts, "model_served": SYNTHETIC_MODEL,
                  "tokens_known": True, "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens,
                  "cached_tokens": None, "reasoning_tokens": None, "cost_usd": None})
    return spans, round(model_start + provider + wait + 0.2, 3), provider, wait


def _record(rng, when, request_id, question, answer, cited, retrieved, grounded, channel, index_id, cold):
    """One log line, built from the same record builder the app uses and then given the extra keys a request log line has."""
    record = tracing._base_record(question, retrieved, answer, grounded, retrieval_mode="dense", model_served=SYNTHETIC_MODEL)
    record["trace_id"] = request_id[:8]
    record["ts"] = when.isoformat(timespec="seconds")
    record["config"].update(llm_model=SYNTHETIC_MODEL, embed_provider="local", dense_search="exact")
    context = generator.format_context(retrieved)
    prompt_tokens = int((len(generator.SYSTEM_PROMPT) + len(context) + len(question) + 30) / rng.uniform(3.9, 4.6))
    completion_tokens = max(4, int(len(answer) / rng.uniform(3.9, 4.6)))
    spans, total, provider, wait = _spans(rng, retrieved, prompt_tokens, completion_tokens, cold)
    record.update({"request_id": request_id, "started_at": when.astimezone().isoformat(timespec="milliseconds"),
                   "ts_utc": when.astimezone().astimezone(timezone.utc).isoformat(timespec="milliseconds"), "channel": channel, "total_ms": total, "spans": spans,
                   "usage": {"model_calls": 1, "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "tokens_known": True,
                             "provider_ms": provider, "wait_ms": wait},
                   "index_id": index_id, "prompt_sha": _sha12(generator.SYSTEM_PROMPT),
                   "chars": {"system": len(generator.SYSTEM_PROMPT), "context": len(context), "question": len(question), "stripped": 0},
                   "sources": list(cited), "status": "ok" if grounded else "refused", "synthetic": True, "origin": "drill-kit"})
    if not grounded:
        record["refusal_cause"] = "model_idk"
    return record


def _moment(rng, start, days):
    """A start time in the window, busier in working hours."""
    day = rng.randrange(days)
    if rng.random() < 0.82:
        hour = rng.choice([9, 10, 10, 11, 11, 12, 13, 14, 14, 15, 15, 16, 17, 18])
    else:
        hour = rng.choice([0, 1, 2, 3, 5, 6, 7, 8, 19, 20, 21, 22, 23])
    return start + timedelta(days=day, hours=hour, minutes=rng.randrange(60), seconds=rng.randrange(60), milliseconds=rng.randrange(1000))


def _unique_id(rng, taken):
    """A 16-digit request id whose first 8 digits (the trace id the older tools show) nobody has used yet. `taken` collects them."""
    while True:
        candidate = f"{rng.getrandbits(64):016x}"
        if candidate[:8] not in taken:
            taken.add(candidate[:8])
            return candidate


def _fill(template):
    """A template's {30}-style slots as plain numbers. The figures were checked against the corpus by check_facts."""
    return re.sub(r"\{(\d+)\}", lambda match: match.group(1), template)


def generate(seed=None, n=3000, days=28, end=None, corpus_dir=None):
    """Build a drill: returns {"records", "meta", "complaint", "plant_id", "requests_text"}. `seed` makes it reproducible, which also makes
    the answer reproducible, so only tests pass one; by default it comes from the operating system's randomness."""
    corpus_dir = corpus_dir or settings.corpus_dir
    seed = int.from_bytes(os.urandom(8), "big") if seed is None else seed
    rng = random.Random(seed)
    check_facts(corpus_dir)
    corpus = _Corpus(corpus_dir)
    if not corpus.fillers:
        raise RuntimeError(f"the drill needs {HANDBOOK} in the corpus: its repeated boilerplate is what crowds the real passage out")
    end = (end or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None) - timedelta(days=1)       # midnight, so every hour below is that hour
    start = end - timedelta(days=days)
    index_id = f"{len(corpus.chunks)}:{_sha12(str(_corpus_fingerprint(corpus_dir)))}"

    names = [t[0] for t in TOPICS] + ["refusal"]
    weights = [t[1] for t in TOPICS] + [REFUSAL_WEIGHT]
    by_name = {t[0]: t for t in TOPICS}
    plan = []
    for _ in range(n - 1):
        topic = rng.choices(names, weights)[0]
        plan.append(topic)

    records, taken = [], set()

    def new_id():
        return _unique_id(rng, taken)

    def one(topic, when, cold=False):
        channel = rng.choices(["api", "cli", "batch"], [80, 10, 10])[0] if 6 <= when.hour <= 21 else "batch"
        if topic == "refusal":
            question = rng.choice(UNANSWERABLE)
            retrieved = corpus.retrieved(HANDBOOK, "", rng, has_answer=False)
            return _record(rng, when, new_id(), question, generator.IDK, [], retrieved, False, channel, index_id, cold)
        _name, _weight, questions, variants = by_name[topic]
        template, cited, phrase, facts = rng.choice(variants)
        return _record(rng, when, new_id(), rng.choice(questions), _fill(template), cited, corpus.retrieved(cited[0], phrase, rng), True, channel, index_id, cold)

    for topic in plan:
        records.append(one(topic, _moment(rng, start, days)))

    # The planted request: a notice answer whose figure no document states, in the middle of the window, in the afternoon.
    usable = [figure for figure in PLANT_CANDIDATES if not _whole_word_in(corpus_dir, figure)]
    if not usable:
        raise RuntimeError("every candidate figure for the planted answer appears in the corpus; add candidates to PLANT_CANDIDATES")
    figure = rng.choice(usable)
    cited = rng.choice([ACME, HANDBOOK])
    when = start + timedelta(days=rng.randrange(int(days * 0.35), int(days * 0.7)), hours=rng.choice([13, 14, 15, 16]), minutes=rng.randrange(60), seconds=rng.randrange(60),
                             milliseconds=rng.randrange(1000))
    notice_variants = by_name[NOTICE][3]
    template = next(v for v in notice_variants if v[1] == [cited] and "disagree" not in v[0] and "probation" not in v[0].lower())
    plant = _record(rng, when, new_id(), rng.choice(by_name[NOTICE][2]), re.sub(r"\{\d+\}", str(figure), template[0]), [cited],
                    corpus.retrieved(cited, template[2], rng), True, "api", index_id, False)
    records.append(plant)
    records.sort(key=lambda r: (r["ts_utc"], r["request_id"]))

    wrong = violations(records, corpus_dir)
    if [r["request_id"] for r in wrong] != [plant["request_id"]]:
        raise RuntimeError(f"the generator is wrong: the planted answer must be the only violation, found {len(wrong)}")
    requests_text = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    salt = f"{rng.getrandbits(128):032x}"
    drill_id = f"drill-{end.strftime('%Y%m%d')}-{rng.getrandbits(24):06x}"
    window_start = (when - timedelta(days=1)).date()
    document = "employment terms document" if cited == ACME else "employee handbook"
    complaint = (f"Subject: a notice period that did not match the policy\n\n"
                 f"A colleague in People Operations says that sometime between {window_start.strftime('%d %B')} and {(when + timedelta(days=1)).date().strftime('%d %B %Y')} the assistant "
                 f"gave them a notice period that did not match the policy documents. They think the answer named the {document}. They did not keep a screenshot and "
                 f"cannot remember the number.\n\nPlease find the request, say what was wrong with the answer, and say what you looked at to be sure.\n")
    meta = {"drill_id": drill_id, "version": VERSION, "synthetic": True, "origin": "drill-kit", "generated_at": datetime.now().isoformat(timespec="seconds"),
            "window": {"start": start.isoformat(timespec="seconds"), "end": end.isoformat(timespec="seconds")}, "n_records": len(records),
            "corpus_fingerprint": _corpus_fingerprint(corpus_dir),
            "real": ["the question wording is the kind of thing people ask", "the passages in each record are real passages of the corpus", "the documents and the figures the correct answers state"],
            "invented": ["every request, its time, its channel and its timings", "the tokens (a quarter of the characters) and the model name", "which requests were wrong"],
            "salt": salt, "commitment": hashlib.sha256((salt + plant["request_id"] + hashlib.sha256(requests_text.encode("utf-8")).hexdigest()).encode("utf-8")).hexdigest()}
    return {"records": records, "meta": meta, "complaint": complaint, "plant_id": plant["request_id"], "requests_text": requests_text}


def commitment(salt, request_id, requests_text):
    """What a guess is checked against: the same hash the generator stored, recomputed for the guessed request id."""
    return hashlib.sha256((salt + request_id + hashlib.sha256(requests_text.encode("utf-8")).hexdigest()).encode("utf-8")).hexdigest()


def write(drill, out_dir):
    """Write requests.jsonl, complaint.txt and drill-meta.json into `out_dir`. The planted id is in none of them in the clear."""
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "requests.jsonl"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(drill["requests_text"])
    with open(os.path.join(out_dir, "complaint.txt"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(drill["complaint"])
    with open(os.path.join(out_dir, "drill-meta.json"), "w", encoding="utf-8", newline="\n") as handle:
        json.dump(drill["meta"], handle, indent=1)
