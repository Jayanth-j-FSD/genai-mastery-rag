"""The eval cases: what the app is asked, and what a good answer looks like.

Week 4 already has 32 labelled questions (`tests/eval_set.py`). Week 6 reuses them
and adds what scoring a whole ANSWER needs on top of "was the right document fetched":

  problem_type  what kind of thing could go wrong ("exact-string", "conflicting-documents", ...).
                Scores are reported per type, so a change that helps one kind and hurts another is
                visible instead of averaged away. These labels are provisional: your Week 5
                taxonomy will name the real problems, and any label works here.
  reference     a short answer drafted from the documents, meant to be
                reviewed by you. The judge and the blind grading sheet both show it, so a wrong
                reference would mislead both.
  expect_all    phrases that must ALL appear (for list answers like "development, testing, production").
  origin        where the case came from: "week4", "week6" (new), or "week5:<trace id>" (one of your
                real failures, turned into a permanent test by scripts/make_regressions.py).

Cases whose `expected_sources` is empty are questions the documents cannot answer: the only correct
reply is "I don't know".
"""
import json
import os

from app.config import BASE_DIR
from tests.eval_set import CASES as WEEK4_CASES

ACME_LEAVE = "Acme-Leave-Policy-2026.md"
NEXORA = "Nexora_Tech_Azure_Cloud_Data_Access_Policy.md"

REGRESSIONS_PATH = os.path.join(BASE_DIR, "evals", "regressions.json")
LOGGED_FAILURES_NAME = "logged_failures.json"          # Week 11: failures found in the request log; it sits beside the Week 5 regressions file

# What kind of problem each Week 4 case exercises. Written once, here, so a reviewer can disagree.
PROBLEM_TYPES = {
    "code-err4032": "exact-string", "exact-security-email": "exact-string",
    "exact-settings-path": "exact-string", "exact-policy-id": "exact-string",
    "acronym-mfa": "exact-string", "acronym-pim": "exact-string",
    "paraphrase-usb": "paraphrase", "paraphrase-hacked": "paraphrase",
    "paraphrase-receipt-window": "paraphrase", "paraphrase-retirement": "paraphrase",
    "ambiguous-home-office": "single-fact", "detail-sick-days": "single-fact",
    "detail-carryover-expiry": "single-fact", "detail-parental-leave": "single-fact",
    "detail-notice-acme": "single-fact", "track-remote-eligibility": "single-fact",
    "track-internet-claim": "single-fact", "track-nexora-key-vault": "single-fact",
    "ambiguous-leave-days": "conflicting-documents", "ambiguous-notice-period": "conflicting-documents",
    "ambiguous-learning-budget": "conflicting-documents",
    "negative-carryover-limit": "careful-reading", "track-nexora-classification": "list-answer",
    "handbook-probation": "crowded-handbook", "handbook-casual-leave": "crowded-handbook",
    "handbook-holidays": "crowded-handbook", "handbook-breach-hours": "crowded-handbook",
    "handbook-pip": "crowded-handbook",
    "absent-bonus": "absent-topic", "absent-dress-code": "absent-topic",
    "absent-azure-subscription-id": "absent-topic", "absent-azure-admin-limit": "absent-topic",
}

# A human-written reference answer per case. Every fact was read out of the named documents.
REFERENCES = {
    "code-err4032": "ERR-4032 means the data source connection timed out. Retry after 60 seconds; if it persists, check the source credentials in Settings > Connections.",
    "exact-security-email": "security@northwind.example is where a suspected security incident must be reported, within 1 hour.",
    "exact-settings-path": "Check the source credentials in Settings > Connections.",
    "exact-policy-id": "NEXORA-CLOUD-SEC-001 is Nexora Tech's Azure Cloud Data Access and Security Policy: how access to data and cloud resources hosted on Azure is managed.",
    "acronym-mfa": "Yes. Multi-factor authentication is required for all company accounts (the handbook says it is mandatory for corporate email, source-code repositories, VPN access and production administration tools).",
    "acronym-pim": "Microsoft Entra Privileged Identity Management (PIM) is used to protect and minimise privileged access.",
    "paraphrase-usb": "No. Customer data must never be copied to personal devices, and a USB stick is a personal device.",
    "paraphrase-hacked": "Report a suspected security incident to security@northwind.example within 1 hour. The handbook says a suspected personal-data incident goes to the Security team within 4 hours.",
    "paraphrase-receipt-window": "Submit the expense within 30 days of purchase, with a receipt.",
    "paraphrase-retirement": "The pension match starts after 3 months of employment.",
    "ambiguous-home-office": "Home-office equipment is reimbursed up to $500 per year.",
    "ambiguous-leave-days": "The Acme leave policy gives 18 days a year, while the handbook and benefits.md say 24. The documents disagree.",
    "ambiguous-notice-period": "Under the Acme employment terms a permanent employee gives 30 calendar days of written notice; the handbook says 60 calendar days for confirmed employees. The documents disagree.",
    "ambiguous-learning-budget": "The handbook says INR 30,000 per financial year; benefits.md says $1,000 a year. The documents differ.",
    "detail-sick-days": "12 paid sick leave days per calendar year.",
    "negative-carryover-limit": "No. Only up to 10 unused days can be carried forward; days above the limit expire on 31 March unless People Operations approves a written exception.",
    "detail-carryover-expiry": "They expire on 31 March unless a written exception is approved by People Operations.",
    "detail-parental-leave": "16 weeks of paid parental leave.",
    "detail-notice-acme": "30 calendar days of written notice, starting on the date People Operations receives the resignation.",
    "track-remote-eligibility": "After completing 60 days of service.",
    "track-internet-claim": "Up to 50 USD per month, with an itemised receipt, submitted by the tenth day of the following month.",
    "track-nexora-classification": "Public, Internal, Confidential and Restricted.",
    "track-nexora-key-vault": "In an approved secrets-management solution such as Azure Key Vault, never directly in source code.",
    "handbook-probation": "The standard probation period is 6 months, which the company may extend once by up to 3 months.",
    "handbook-casual-leave": "6 days of casual leave per calendar year.",
    "handbook-holidays": "12 designated company holidays.",
    "handbook-breach-hours": "Within 4 hours of discovery.",
    "handbook-pip": "A standard performance improvement plan may run for 60 days.",
    "absent-bonus": "The documents do not say. The correct reply is that it does not know.",
    "absent-dress-code": "The documents do not say. The correct reply is that it does not know.",
    "absent-azure-subscription-id": "The policy does not specify a subscription ID. The correct reply is that it does not know; it must not invent one.",
    "absent-azure-admin-limit": "The policy does not specify a maximum number of administrators. The correct reply is that it does not know.",
    "nexora-environments": "Development, Testing and Production.",
    "nexora-security-role": "The Security Administrator.",
    "nexora-developer-restricted": "No, not directly, unless specifically authorized.",
    "nexora-analyst": "A Data Analyst can read approved business datasets, run approved queries and generate reports. They cannot modify production infrastructure.",
    "nexora-inactive-accounts": "Inactive accounts and unnecessary permissions must be removed.",
    "nexora-storage-container": "No. Least privilege means access at the lowest practical scope, such as the specific container, not the whole subscription.",
    "nexora-prod-to-dev": "Not without appropriate anonymization or security approval.",
    "nexora-prod-approvals": "Business justification, appropriate Azure RBAC permissions, approval from the relevant manager or data owner, logging and monitoring, and periodic access review.",
    "nexora-customer-data-prod": "Customer data may only be accessible to employees whose work requires it. Production database access needs business justification, RBAC permissions, manager or data-owner approval, logging and monitoring and periodic review. Developers must not directly access Restricted production data unless specifically authorized, least privilege applies, and customer data must not be copied into development without approval.",
}

# New in Week 6: the Nexora policy's own questions (tests/nexora_eval_questions.md) that Week 4 did not use.
NEW_CASES = [
    {"id": "nexora-environments", "question": "What are the three Azure environments?",
     "expected_sources": [NEXORA], "expect_contains": [], "expect_all": ["development", "testing", "production"],
     "problem_type": "list-answer", "why_hard": "Three items in a bullet list: an answer that drops one is wrong."},
    {"id": "nexora-security-role", "question": "Which role reviews security configurations and access assignments?",
     "expected_sources": [NEXORA], "expect_contains": ["security administrator"],
     "problem_type": "single-fact", "why_hard": "Five roles are described; only one reviews configurations."},
    {"id": "nexora-developer-restricted", "question": "Can a developer directly access Restricted production data?",
     "expected_sources": [NEXORA], "expect_contains": ["unless", "authorized", "authorised"],
     "problem_type": "careful-reading", "why_hard": "The answer is a no with an exception, and models often drop the exception."},
    {"id": "nexora-analyst", "question": "What permissions does a Data Analyst have?",
     "expected_sources": [NEXORA], "expect_contains": [], "expect_all": ["read", "quer", "report"],
     "problem_type": "list-answer", "why_hard": "Three permissions plus a limit."},
    {"id": "nexora-inactive-accounts", "question": "What should happen to inactive accounts?",
     "expected_sources": [NEXORA], "expect_contains": ["removed", "remove"],
     "problem_type": "single-fact", "why_hard": "One short sentence in the access-review section."},
    {"id": "nexora-storage-container", "question": "A developer only needs to read files from one Azure Storage container. Should the developer receive access to the entire Azure subscription?",
     "expected_sources": [NEXORA], "expect_contains": [],
     "problem_type": "careful-reading", "why_hard": "Needs the least-privilege principle applied to a new example; judged, not string-matched."},
    {"id": "nexora-prod-to-dev", "question": "Can production data be copied into a development environment?",
     "expected_sources": [NEXORA], "expect_contains": ["anonymi", "approval"],
     "problem_type": "careful-reading", "why_hard": "The rule appears in two sections with different wording."},
    {"id": "nexora-prod-approvals", "question": "What approvals are required before accessing production data?",
     "expected_sources": [NEXORA], "expect_contains": [], "expect_all": ["justification", "approval", "review"],
     "problem_type": "list-answer", "why_hard": "A numbered list of five requirements."},
    {"id": "nexora-customer-data-prod", "question": "What restrictions apply when a developer wants to access customer data stored in production?",
     "expected_sources": [NEXORA], "expect_contains": [],
     "problem_type": "careful-reading", "why_hard": "Needs three sections combined: production access, customer data and least privilege."},
]


def _from_week4(case):
    merged = dict(case)
    merged["problem_type"] = PROBLEM_TYPES.get(case["id"], "other")
    merged["origin"] = "week4"
    return merged


def load_regressions(path=None):
    """Cases made from your own Week 5 failures. [] until evals/regressions.json exists."""
    path = path or REGRESSIONS_PATH
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return json.load(handle).get("cases", [])


def logged_failures_path(regressions_path=None):
    """Where the logged failures live: beside the regressions file, so a test that points the regressions somewhere else (to switch
    them off) switches these off with it."""
    return os.path.join(os.path.dirname(regressions_path or REGRESSIONS_PATH), LOGGED_FAILURES_NAME)


def load_logged_failures(path=None):
    """Cases made from real failures found in the request log (scripts/failure_to_test.py writes them). [] until the file exists.

    Every case must say what a correct answer looks like: expected documents, or an explicit should_refuse. Without that rule a case
    with nothing filled in would quietly become a REFUSAL case in all_cases, and a refusal-only check would pass the very failure it was
    made from."""
    path = path or logged_failures_path()
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        found = json.load(handle).get("cases", [])
    for case in found:
        if not case.get("id") or not str(case.get("question", "")).strip():
            raise ValueError(f"a logged failure needs an id and a question: {case!r}")
        if not case.get("expected_sources") and case.get("should_refuse") is not True:
            raise ValueError(f"logged failure {case['id']!r} has no expected_sources and does not set should_refuse: it would be scored as a refusal")
        case.setdefault("origin", f"week11:{case['id']}")
        case.setdefault("problem_type", "logged-failure")
        case.setdefault("whole_words", True)
    return found


def all_cases(regressions_path=None):
    """Every case, Week 4's first, then Week 6's new ones, then the Week 5 regressions, then the failures found in the log (Week 11)."""
    cases = [_from_week4(case) for case in WEEK4_CASES]
    for case in NEW_CASES:
        cases.append({**case, "origin": "week6"})
    cases.extend(dict(case) for case in load_regressions(regressions_path))
    cases.extend(dict(case) for case in load_logged_failures(logged_failures_path(regressions_path)))
    for case in cases:
        case.setdefault("expected_sources", [])
        case.setdefault("expect_contains", [])
        case.setdefault("expect_all", [])
        case.setdefault("problem_type", "other")
        case.setdefault("reference", REFERENCES.get(case["id"], ""))
        explicit_refuse = case.get("should_refuse") is True
        # A Week 5 failure with no expectations filled in yet cannot be scored by rules beyond
        # "did it answer": it is still run and judged, and the run says so.
        case["needs_expected"] = (str(case.get("origin", "")).startswith("week5")
                                  and not case["expected_sources"] and not explicit_refuse)
        case["should_refuse"] = explicit_refuse or (not case["expected_sources"] and not case["needs_expected"])
    ids = [case["id"] for case in cases]
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise ValueError(f"Duplicate eval case ids: {duplicates}")
    return cases
