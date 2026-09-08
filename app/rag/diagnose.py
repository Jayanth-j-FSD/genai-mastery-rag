"""Week 4 addition — sort a failure into one of the two kinds, with evidence.

"the app is sometimes wrong" cannot be fixed. There are two very
different kinds of wrong, and they need opposite fixes:

  RETRIEVAL   the app fetched the WRONG DOCUMENT. The answer model never even saw
              the right text, so a smarter model would change nothing. Fix the search.
  GENERATION  the app fetched the RIGHT DOCUMENT and still answered badly (or refused,
              or answered when it should have refused). Fix the prompt or the chunking.

This module decides which one a given question is, and hands back the evidence that
proves it: what was fetched, at what rank, and what the app actually said.
"""
import re

from app.config import settings
from app.rag import generator, retriever

KIND_PASS = "PASS"
KIND_RETRIEVAL = "RETRIEVAL"      # wrong document fetched
KIND_GENERATION = "GENERATION"    # right document, wrong answer
# Used only when the answer model was deliberately skipped: retrieval was fine, but the
# answer was never graded, so calling it a PASS would claim more than was measured.
KIND_RETRIEVAL_OK = "RETRIEVAL OK"

# The verdicts that are not failures. Callers filtering for failures should use this.
NON_FAILURE_KINDS = (KIND_PASS, KIND_RETRIEVAL_OK)


def _normalize(text: str) -> str:
    """Lowercase and flatten a string so expectations match real answers.

    Removes thousands separators and straightens curly apostrophes, so "$1,000"
    matches "$1000" and "don't" matches "don’t".
    """
    cleaned = (text or "").lower().replace("’", "'").replace(",", "")
    return re.sub(r"\s+", " ", cleaned).strip()


def _first_match(answer: str, expectations):
    """Return the first expected phrase present in the answer, or None."""
    normalized_answer = _normalize(answer)
    for expectation in expectations or []:
        normalized_expectation = _normalize(expectation)
        if normalized_expectation and normalized_expectation in normalized_answer:
            return expectation
    return None


def snippet(text: str, limit: int = 160) -> str:
    """A one-line preview of a chunk, for side-by-side reading."""
    flattened = re.sub(r"\s+", " ", text or "").strip()
    return flattened if len(flattened) <= limit else flattened[: limit - 1] + "…"


def _evidence(chunks, expected_sources):
    """Describe what was fetched, and where the expected document landed (if at all)."""
    rows = []
    expected_rank = None
    for rank, chunk in enumerate(chunks, start=1):
        source = chunk.get("source", "unknown")
        if expected_rank is None and source in expected_sources:
            expected_rank = rank
        rows.append({
            "rank": rank,
            "source": source,
            "score": chunk.get("score"),
            "retrievers": chunk.get("retrievers", []),
            "dense_rank": chunk.get("dense_rank"),
            "keyword_rank": chunk.get("keyword_rank"),
            "snippet": snippet(chunk.get("text", "")),
        })
    return rows, expected_rank


def classify(case, mode: str = None, k: int = None, call_model: bool = True):
    """Diagnose one labelled question. Returns a dict carrying the verdict and evidence.

    `case` is a dict from tests/eval_set.py:
        question          the question to ask
        expected_sources  list of documents that legitimately answer it;
                          an EMPTY list means "not in the corpus, must refuse"
        expect_contains   phrases a correct answer should contain (any one is enough)

    `k` defaults to `settings.top_k` — the number of chunks the answer model really
    sees — because that is what decides whether the right document reached it.
    Set `call_model=False` to skip the answer model: cheaper, but then a retrieval
    success cannot be graded any further than "the right document was fetched".
    """
    depth = k or settings.top_k
    expected_sources = list(case.get("expected_sources") or [])
    must_refuse = not expected_sources

    chunks = retriever.retrieve_for_mode(case["question"], depth, mode)
    retrieved, expected_rank = _evidence(chunks, expected_sources)

    result = {
        "question": case["question"],
        "mode": (mode or settings.retrieval_mode),
        "k": depth,
        "expected_sources": expected_sources,
        "must_refuse": must_refuse,
        "expected_rank": expected_rank,
        "retrieved": retrieved,
        "answer": None,
        "grounded": None,
        "matched": None,
        "kind": None,
        "why": "",
    }

    # Retrieval verdict first: if the right document never arrived, nothing the answer
    # model does can be blamed — and for an in-corpus question that is the whole story.
    if not must_refuse and expected_rank is None:
        result["kind"] = KIND_RETRIEVAL
        got = ", ".join(row["source"] for row in retrieved) or "nothing"
        result["why"] = (
            f"Expected one of {expected_sources} in the top {depth}, but got: {got}. "
            "The answer model never saw the right text, so this is a search problem."
        )

    if not call_model:
        # Retrieval-only run: report exactly what retrieval alone can prove, no more.
        if result["kind"] is None:
            if must_refuse:
                result["why"] = ("This case is graded on whether the app refuses, which "
                                 "needs the answer model. Re-run without --no-model.")
            else:
                result["kind"] = KIND_RETRIEVAL_OK
                result["why"] = (f"The expected document was fetched at rank "
                                 f"{expected_rank}; the answer itself was not graded.")
        return result

    answer_text, _sources, grounded = generator.generate_answer(case["question"], chunks)
    result["answer"] = answer_text
    result["grounded"] = grounded

    # A question whose answer is not in the corpus: the only correct behaviour is refusal.
    if must_refuse:
        if grounded:
            result["kind"] = KIND_GENERATION
            result["why"] = (
                "This question is not answerable from the corpus, but the app answered "
                "instead of refusing — a grounding failure, not a search failure."
            )
        else:
            result["kind"] = KIND_PASS
            result["why"] = "Not in the corpus, and the app correctly said it does not know."
        return result

    # In-corpus question. If retrieval already failed we kept the verdict; only add
    # what the app said instead, as evidence.
    if result["kind"] == KIND_RETRIEVAL:
        result["why"] += f' It answered: "{snippet(answer_text, 120)}"'
        return result

    matched = _first_match(answer_text, case.get("expect_contains"))
    result["matched"] = matched
    if not grounded:
        result["kind"] = KIND_GENERATION
        result["why"] = (
            f"The right document was fetched (rank {expected_rank}) but the app refused "
            "to answer. The facts were present, so this is a grounding failure."
        )
    elif matched:
        result["kind"] = KIND_PASS
        result["why"] = f'Right document at rank {expected_rank}, and the answer contains "{matched}".'
    else:
        result["kind"] = KIND_GENERATION
        result["why"] = (
            f"The right document was fetched (rank {expected_rank}) but the answer did not "
            f"contain any of {case.get('expect_contains')} — right document, wrong answer."
        )
    return result
