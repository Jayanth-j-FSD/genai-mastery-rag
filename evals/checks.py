"""Assertion checks: the simple, free, rule-based scoring of one answer.

The Week 6 brief says to do the cheap checks first. A rule can tell you, with no
AI call at all, whether the answer cited the right document, whether it refused when it should
have (and answered when it should have), and whether it contains the facts it must. Only the
things a rule cannot judge (is the answer faithful? is it complete?) are left to the AI judge.

`result` is what the app produced for one case:
    {"answer": str, "grounded": bool, "sources": [document names], "retrieved": [{"source", "text"}]}
Each check returns {"name", "passed", "detail"}.
"""
import re

from app.rag.diagnose import _normalize

# A number: digits with optional thousands commas and decimals, e.g. 18, 30,000, 0.5.
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Citations such as "[source: Acme-Leave-Policy-2026.md]" carry digits (the year) that are not claims.
_CITATION_RE = re.compile(r"\[source:[^\]]*\]", re.IGNORECASE)
# The "1." or "2)" that numbers a list item is formatting, not a figure the model made up.
_LIST_MARKER_RE = re.compile(r"(?m)^\s*\(?\d{1,2}[.)]\s+")


def _clean(text):
    """Lowercase, drop markdown emphasis and thousands separators so "**$1,000**" matches "$1000"."""
    return _normalize((text or "").replace("*", ""))


def _check(name, passed, detail):
    return {"name": name, "passed": bool(passed), "detail": detail}


def refusal_check(case, result):
    """Did the app refuse exactly when it should? Absent topics must be refused, answerable ones answered."""
    if case["should_refuse"]:
        return _check("refusal", not result["grounded"],
                      "refused, as required" if not result["grounded"]
                      else "answered a question the documents cannot answer")
    return _check("refusal", result["grounded"],
                  "answered" if result["grounded"] else "refused a question the documents do answer")


def source_check(case, result):
    """Does the answer cite at least one document that legitimately answers the question?

    A case that needs several documents (two facts in two documents, or a conflict between them) sets
    `require_all_sources`: then every expected document must be cited, not just one of them.
    """
    if case.get("require_all_sources"):
        missing = [name for name in case["expected_sources"] if name not in result["sources"]]
        return _check("cites_expected_source", not missing,
                      "cited every expected document" if not missing
                      else f"did not cite {missing}; cited {result['sources'] or 'nothing'}")
    cited = [name for name in result["sources"] if name in case["expected_sources"]]
    return _check("cites_expected_source", bool(cited),
                  f"cited {cited[0]}" if cited else f"cited {result['sources'] or 'nothing'}, "
                                                    f"expected one of {case['expected_sources']}")


def _contains(answer, phrase, whole_words):
    """Is the phrase in the answer? Plain substring by default. With `whole_words` it must stand on its own, so
    "7 calendar days" is not found inside "17 calendar days" and "3 december" is not found inside "13 december"."""
    phrase = _clean(phrase)
    if not whole_words:
        return phrase in answer
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", answer) is not None


def contains_phrase(text, phrase, whole_words=False):
    """Is the phrase in the text, tidied exactly as the checks tidy an answer? For screens that read passages, not answers."""
    return _contains(_clean(text), phrase, whole_words)


def fact_check(case, result):
    """Does the answer contain the facts it must? Any one of expect_contains, and all of expect_all.

    A case may set `whole_words` to match its phrases as whole words (the default is a plain substring, which is
    what the Week 6 cases were scored with).
    """
    answer = _clean(result["answer"])
    whole = bool(case.get("whole_words"))
    missing_all = [phrase for phrase in case["expect_all"] if not _contains(answer, phrase, whole)]
    any_ok = (not case["expect_contains"]
              or any(_contains(answer, phrase, whole) for phrase in case["expect_contains"]))
    if missing_all:
        return _check("has_expected_fact", False, f"missing required phrase(s): {missing_all}")
    if not any_ok:
        return _check("has_expected_fact", False, f"contains none of {case['expect_contains']}")
    return _check("has_expected_fact", True, "contains the expected fact")


def invented_numbers(result, question):
    """Numbers in the answer that appear neither in the retrieved text nor in the question.

    A cheap hallucination alarm: a figure the model was never shown is a figure it made up (or
    computed, which this app is not asked to do). Reported as a warning, not as a failure, because
    a harmless derived number would otherwise fail a good answer.
    """
    context = " ".join(chunk.get("text", "") for chunk in result.get("retrieved", []))
    known = {number.replace(",", "") for number in _NUMBER_RE.findall(context + " " + (question or ""))}
    body = _LIST_MARKER_RE.sub("", _CITATION_RE.sub(" ", result["answer"]))
    return sorted({number.replace(",", "") for number in _NUMBER_RE.findall(body)} - known)


def forbid_check(case, result):
    """Does the answer avoid every phrase the case forbids? (Week 11, for a failure that was a wrong figure or a wrong claim.)

    Phrases match as whole words, so forbidding "45" does not trip on "145". The known limit: it cannot tell "45 days" from "not 45
    days", because it reads words, not meaning, so a correction that quotes the wrong figure to deny it fails too. Forbid a phrase the
    right answer never needs to say."""
    answer = _clean(result["answer"])
    found = [phrase for phrase in case["forbid_contains"] if _contains(answer, phrase, True)]
    return _check("avoids_forbidden_phrase", not found, "contains none of the forbidden phrases" if not found else f"contains the forbidden phrase(s): {found}")


def check_case(case, result):
    """Run the checks that apply to this case. Returns (checks, passed, warnings)."""
    checks = [refusal_check(case, result)]
    if not case["should_refuse"] and not case.get("needs_expected"):
        checks.append(source_check(case, result))
        if case["expect_contains"] or case["expect_all"]:
            checks.append(fact_check(case, result))
    if case.get("forbid_contains"):                      # beside the older checks: a case without this key is scored exactly as before
        checks.append(forbid_check(case, result))
    warnings = []
    if case.get("needs_expected"):
        warnings.append("no expected facts yet: only the refusal check and the judge apply "
                        "(fill expected_sources / expect_contains in evals/regressions.json)")
    extra = invented_numbers(result, case["question"]) if result["grounded"] else []
    if extra:
        warnings.append(f"numbers in the answer not found in the context: {extra}")
    return checks, all(c["passed"] for c in checks), warnings
