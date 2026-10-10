"""The LLM judge: one AI call that grades another AI's answer.

Some things a rule cannot check. Is the answer faithful to the documents, or did it
add a claim nobody wrote? Did it answer the question that was asked? When two documents disagree,
did it say so? A second model call can read the question, the documents the app was given and the
app's answer, and give a verdict.

Three choices worth knowing about, because the brief names them:

  Binary, not 1 to 10. A pass/fail verdict is easy for a human to agree with, which is exactly what
  validating a judge needs. A 1 to 10 score drifts (is this a 6 or a 7?) and cannot be validated
  without a rubric for every number. Deferred, with that reason.
  Reason first, then verdict. This is the G-Eval idea: asking for the reasoning before the verdict
  makes the verdict follow from something instead of being a guess.
  A different model from the one that wrote the answer (JUDGE_MODEL). A model grading its own
  family's output tends to like it. It does not remove the bias, and the validation step below
  is what tells you whether to trust the number at all.

The judge is only as good as its agreement with a human. Until `scripts/validate_judge.py` has
compared it with your own grading, its numbers are not evidence.
"""
import hashlib
import json
import re

from app import llm
from app.config import settings

# Bump this when the rubric changes, so cached verdicts from the old rubric are not reused.
RUBRIC_VERSION = "1"

SYSTEM_PROMPT = (
    "You are a strict grader of a question-answering system that answers from company policy "
    "documents. You are given a QUESTION, the CONTEXT passages the system was shown (each tagged "
    "with its source document), the system's ANSWER, and usually a REFERENCE answer written by a "
    "human who read the documents.\n"
    "Decide whether the ANSWER is acceptable. Check these four things in order:\n"
    "1. Faithful: every factual claim in the ANSWER is supported by the CONTEXT. An invented "
    "number, date or rule makes it fail, even if it sounds plausible.\n"
    "2. Responsive: it answers the question that was asked, with the specific fact requested, "
    "not a different or adjacent fact. A missing part of a list answer fails.\n"
    "3. Honest about absence: if the CONTEXT does not contain the answer, the correct ANSWER says "
    "it does not know, and a confident answer fails. If the CONTEXT does contain the answer, a "
    "refusal fails.\n"
    "4. Conflicts: if the CONTEXT contains documents that disagree, an answer that reports the "
    "disagreement or clearly names the document it relies on passes. One that silently picks a "
    "number without saying which document it came from fails.\n"
    "The ANSWER does not have to match the REFERENCE word for word; it has to say the same thing.\n"
    'Reply with ONLY a JSON object: {"reason": "<one short sentence>", "verdict": "pass" or "fail"}. '
    "Write the reason first, then the verdict."
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def build_prompt(question, retrieved, answer, reference=""):
    """The user message: the question, what the app was shown, what it said, and the human reference."""
    context = "\n\n".join(f"[source: {chunk['source']}]\n{chunk['text']}" for chunk in retrieved) or "(nothing was retrieved)"
    parts = [f"QUESTION:\n{question}", f"CONTEXT:\n{context}"]
    if reference:
        parts.append(f"REFERENCE:\n{reference}")
    parts.append(f"ANSWER:\n{answer}")
    return "\n\n".join(parts)


def parse_verdict(text):
    """Pull {"verdict", "reason"} out of the judge's reply. Tolerates code fences and extra words.

    Returns verdict "error" (never a guess) when no pass/fail can be read, so an unreadable reply
    is counted and shown instead of quietly becoming a pass or a fail.
    """
    match = _JSON_RE.search(text or "")
    if match:
        try:
            data = json.loads(match.group(0))
            verdict = str(data.get("verdict", "")).strip().lower()
            if verdict in ("pass", "fail"):
                return {"verdict": verdict, "reason": str(data.get("reason", "")).strip()}
        except (json.JSONDecodeError, AttributeError):
            pass
    return {"verdict": "error", "reason": f"unreadable judge reply: {(text or '')[:120]!r}"}


def cache_key(model, question, retrieved, answer, reference):
    """Everything the verdict depends on, so a cached verdict is reused only for identical input."""
    payload = json.dumps([RUBRIC_VERSION, model, question, [(c["source"], c["text"]) for c in retrieved],
                          answer, reference], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def judge_model():
    """JUDGE_MODEL, or the answer model when none is set (works, but the bias above is stronger)."""
    return settings.judge_model or settings.llm_model


def judge_answer(question, retrieved, answer, reference="", model=None):
    """Grade one answer. Returns {"verdict": "pass"|"fail"|"error", "reason", "model"}."""
    model = model or judge_model()
    rpm = settings.judge_rpm or settings.llm_rpm
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(question, retrieved, answer, reference)}]
    response = llm.chat(messages, model=model, rpm=rpm, temperature=0)
    verdict = parse_verdict(llm.text_of(response))
    verdict["model"] = model
    return verdict
