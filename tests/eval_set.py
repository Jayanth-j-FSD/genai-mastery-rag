"""Week 4 — the labelled question set the measurements run against.

To prove a change helped you need questions with *known* right answers.
Each case below records the question, which document(s) legitimately answer it, and a
phrase a correct answer must contain. Every expected value here was read out of the
files in `data/corpus/` — nothing is guessed.

Some cases are deliberately built to fail meaning-only search: a bare code like
`ERR-4032` or an exact address like `security@northwind.example` carries almost no
"meaning" to embed. Others are built the opposite way (a question that shares no
words with the document) so that keyword search alone would miss them. That mix is
what makes the before/after comparison honest instead of rigged.

`favours` is a PREDICTION written before running anything: which retriever should win
this case. `scripts/eval_retrieval.py` reports whether each prediction held, so a
wrong hypothesis is visible rather than quietly forgotten.

When you swap in your own track's documents, rewrite these cases the same way:
read the document, copy the fact, and record which file it came from.

--- What changed since Week 4 (2026-10-11), and why ---
The corpus changed after this set was first written: `annual-leave.md` and `remote-work.md`
were removed and the HR track documents were added. Cases that pointed at deleted files
would have been reported as retrieval failures that no search could ever fix, so they were
replaced, before anything was measured, by cases of the SAME KIND on the current files:

    old id                       replaced by             kind (unchanged)
    exact-code-freeze            exact-policy-id         exact string, favours keyword
    exact-collaboration-day      acronym-pim             exact string, favours keyword
    negative-carryover-payout    negative-carryover-limit  right document, negative statement
    detail-december-forfeit      detail-carryover-expiry   right document, specific detail
    absent-parental-leave        detail-parental-leave    now answered by the Acme leave policy
    absent-sick-days             detail-sick-days         now answered (Acme policy and handbook)
    absent-notice-period         ambiguous-notice-period  now answered, and the documents disagree

The other eleven original ids are kept (two with an extra acceptable document). New cases cover
the track documents: the Acme policies, the Northstar remote-work policy, the Nexora cloud
policy, and facts that live only in the large, heavily repeated handbook. The refusal cases that
became answerable were swapped for questions that really are absent, including the two Nexora
hallucination questions that used to be answerable from the answer key inside the corpus.
"""

# Shorthand for the documents the cases point at (the strings are the exact source names).
ACME_LEAVE = "Acme-Leave-Policy-2026.md"
ACME_TERMS = "Acme-Employment-Terms-2026.md"
REMOTE = "Northstar-Remote-Work-Policy-2026.md"
NEXORA = "Nexora_Tech_Azure_Cloud_Data_Access_Policy.md"
HANDBOOK = "Synthetic_HR_Policy_RAG_Test_Dataset.md"

# expected_sources: documents that legitimately answer it.
#                   An EMPTY list means "not in the corpus — the app must refuse".
# expect_contains:  a correct answer contains at least ONE of these phrases.
# favours:          prediction — "keyword", "dense", or "either".
# evidence:        (optional) exact sentences from the documents that state the fact. Added for the cases
#                   whose accepted phrases are bare numbers ("12", "60"), which appear almost anywhere, so
#                   a unit test can prove the fact itself is still in the document.
# absent_terms:    (refusal cases only) words that prove the topic really is absent;
#                   a unit test fails if any corpus file ever contains one.
CASES = [
    # --- exact strings: the classic weakness of meaning-only search ---
    {
        "id": "code-err4032",
        "question": "ERR-4032",
        "expected_sources": ["support-faq.md"],
        "expect_contains": ["timed out"],
        "favours": "keyword",
        "why_hard": "A bare error code has almost no semantic content to embed.",
    },
    {
        "id": "exact-security-email",
        "question": "What is security@northwind.example used for?",
        "expected_sources": ["security-policy.md"],
        "expect_contains": ["1 hour", "incident"],
        "favours": "keyword",
        "why_hard": "An exact address is a string, not a meaning.",
    },
    {
        "id": "exact-settings-path",
        "question": "What should I check in Settings > Connections?",
        "expected_sources": ["support-faq.md"],
        "expect_contains": ["credentials"],
        "favours": "keyword",
        "why_hard": "An exact UI path only matches on the literal words.",
    },
    {
        "id": "exact-policy-id",
        "question": "What is policy NEXORA-CLOUD-SEC-001 about?",
        "expected_sources": [NEXORA],
        "expect_contains": ["azure", "cloud"],
        "favours": "keyword",
        "why_hard": "A policy id is one exact token and the question carries no topic words at all.",
    },
    {
        "id": "acronym-mfa",
        "question": "Is MFA mandatory?",
        "expected_sources": ["security-policy.md", HANDBOOK],
        "expect_contains": ["required", "mandatory"],
        "favours": "keyword",
        "why_hard": "The documents spell out 'multi-factor authentication'; the query is the acronym.",
    },
    {
        "id": "acronym-pim",
        "question": "What is PIM used for?",
        "expected_sources": [NEXORA],
        "expect_contains": ["privileged"],
        "favours": "keyword",
        "why_hard": "The policy names it once, inside 'Privileged Identity Management (PIM)'; the question gives only the acronym.",
    },

    # --- paraphrases: where meaning-only search earns its place ---
    {
        "id": "paraphrase-usb",
        "question": "Can I copy customer data onto my own USB stick?",
        "expected_sources": ["security-policy.md", REMOTE, NEXORA],
        "expect_contains": ["never", "must not", "not allowed", "prohibited"],
        "favours": "dense",
        "why_hard": "The policies say 'personal devices'; the question says 'USB stick'. No shared words.",
    },
    {
        "id": "paraphrase-hacked",
        "question": "Who do I tell if I think we have been hacked?",
        "expected_sources": ["security-policy.md", HANDBOOK],
        "expect_contains": ["security@northwind.example", "1 hour", "security team"],
        "favours": "dense",
        "why_hard": "'hacked' never appears; the documents say 'security incident' or 'personal-data incident'.",
    },
    {
        "id": "paraphrase-receipt-window",
        "question": "How long do I have to hand in a receipt after buying something?",
        "expected_sources": ["expenses.md", HANDBOOK],
        "expect_contains": ["30 days"],
        "favours": "dense",
        "why_hard": "Different vocabulary for the same rule ('submit within 30 days').",
    },
    {
        "id": "paraphrase-retirement",
        "question": "How long until my retirement contributions start?",
        "expected_sources": ["benefits.md"],
        "expect_contains": ["3 months"],
        "favours": "dense",
        "why_hard": "The document says 'pension match', the question says 'retirement contributions'.",
    },

    # --- facts that live in SEVERAL documents: a fair answer may cite any of them ---
    {
        "id": "ambiguous-home-office",
        "evidence": ["home-office equipment: up to $500 per year"],
        "question": "How much can I claim for home-office equipment?",
        "expected_sources": ["expenses.md"],
        "expect_contains": ["$500", "500"],
        "favours": "either",
        "why_hard": "Only expenses.md states the equipment limit; the remote-work policy covers internet, not equipment.",
    },
    {
        "id": "ambiguous-leave-days",
        "evidence": ["employees receive 18 days of annual leave", "24 days of annual leave per calendar year"],
        "question": "How many annual leave days do full-time employees get?",
        "expected_sources": [ACME_LEAVE, HANDBOOK, "benefits.md"],
        "expect_contains": ["18", "24"],
        "favours": "either",
        "why_hard": "Three documents answer with two different numbers: 18 (Acme) and 24 (handbook, benefits.md).",
    },
    {
        "id": "ambiguous-notice-period",
        "evidence": ["30 calendar days of written notice", "60 calendar days for confirmed employees"],
        "question": "How many days of notice must a confirmed or permanent employee give before resigning?",
        "expected_sources": [ACME_TERMS, HANDBOOK],
        "expect_contains": ["30", "60"],
        "favours": "either",
        "why_hard": "Acme says 30 calendar days, the handbook says 60. Each is right for its own company.",
    },
    {
        "id": "ambiguous-learning-budget",
        "evidence": ["inr 30,000 per financial year", "annual learning budget of $1,000"],
        "question": "What is the annual learning and certification budget per employee?",
        "expected_sources": [HANDBOOK, "benefits.md"],
        "expect_contains": ["30,000", "1,000"],
        "favours": "either",
        "why_hard": "INR 30,000 in the handbook and $1,000 in benefits.md.",
    },
    {
        "id": "detail-sick-days",
        "evidence": ["12 paid sick-leave days", "12 days of sick leave"],
        "question": "How many sick leave days do employees get per year?",
        "expected_sources": [ACME_LEAVE, HANDBOOK],
        "expect_contains": ["12"],
        "favours": "either",
        "why_hard": "Both documents say 12, but the handbook also lists 24 and 6 for other kinds of leave.",
    },

    # --- right document, but the answer has to read carefully ---
    {
        "id": "negative-carryover-limit",
        "question": "Can I carry forward all of my unused annual leave days into next year?",
        "expected_sources": [ACME_LEAVE],
        "expect_contains": ["10", "up to", "expire"],
        "favours": "either",
        "why_hard": "The answer is a limit ('up to 10') with a consequence ('expire'), not a plain yes or no.",
    },
    {
        "id": "detail-carryover-expiry",
        "question": "When do unused leave days above the carry-forward limit expire?",
        "expected_sources": [ACME_LEAVE],
        "expect_contains": ["31 march"],
        "favours": "either",
        "why_hard": "Requires the specific date, not the general carry-forward rule.",
    },
    {
        "id": "detail-parental-leave",
        "question": "How many weeks of paid parental leave are available?",
        "expected_sources": [ACME_LEAVE],
        "expect_contains": ["16 weeks"],
        "favours": "either",
        "why_hard": "One line at the end of a five-section policy.",
    },
    {
        "id": "detail-notice-acme",
        "evidence": ["30 calendar days of written notice"],
        "question": "Under the Acme employment terms, how many days of written notice must a permanent employee give?",
        "expected_sources": [ACME_TERMS],
        "expect_contains": ["30"],
        "favours": "either",
        "why_hard": "Naming the company is the only thing separating it from the handbook's 60 days.",
    },

    # --- the track documents: remote work and the cloud policy ---
    {
        "id": "track-remote-eligibility",
        "evidence": ["after completing 60 days of service"],
        "question": "After how many days of service may an employee request remote work?",
        "expected_sources": [REMOTE],
        "expect_contains": ["60"],
        "favours": "either",
        "why_hard": "The handbook has a remote-work section too, but its eligibility text is generic boilerplate.",
    },
    {
        "id": "track-internet-claim",
        "evidence": ["up to 50 usd per month"],
        "question": "How much can I claim each month for internet used for remote work?",
        "expected_sources": [REMOTE],
        "expect_contains": ["50"],
        "favours": "either",
        "why_hard": "Competes with the expenses policy and with the handbook's expense sections.",
    },
    {
        "id": "track-nexora-classification",
        "question": "What are the four data classification levels?",
        "expected_sources": [NEXORA],
        "expect_contains": ["restricted"],
        "favours": "either",
        "why_hard": "The four levels are rows of one table; a chunk boundary through it loses some of them.",
    },
    {
        "id": "track-nexora-key-vault",
        "question": "Where should Azure access keys and database passwords be stored?",
        "expected_sources": [NEXORA],
        "expect_contains": ["key vault"],
        "favours": "either",
        "why_hard": "The answer is one sentence at the end of a section about secrets.",
    },

    # --- facts that exist ONLY inside the handbook, whose other lines are repeated 136 times ---
    {
        "id": "handbook-probation",
        "question": "What is the standard probation period?",
        "expected_sources": [HANDBOOK],
        "expect_contains": ["6 months"],
        "favours": "either",
        "why_hard": "The one real fact in a section whose other lines are identical boilerplate repeated 136 times.",
    },
    {
        "id": "handbook-casual-leave",
        "evidence": ["6 days of casual leave per calendar year"],
        "question": "How many days of casual leave do employees get per year?",
        "expected_sources": [HANDBOOK],
        "expect_contains": ["6 days"],
        "favours": "either",
        "why_hard": "Only the handbook has casual leave, among many near-identical leave paragraphs.",
    },
    {
        "id": "handbook-holidays",
        "evidence": ["12 designated company holidays"],
        "question": "How many designated company holidays does the company publish each year?",
        "expected_sources": [HANDBOOK],
        "expect_contains": ["12"],
        "favours": "either",
        "why_hard": "A single number inside repeated policy boilerplate.",
    },
    {
        "id": "handbook-breach-hours",
        "question": "Within how many hours must a suspected personal-data incident be reported to the Security team?",
        "expected_sources": [HANDBOOK],
        "expect_contains": ["4 hours"],
        "favours": "either",
        "why_hard": "The security policy has a different deadline (1 hour) for security incidents.",
    },
    {
        "id": "handbook-pip",
        "question": "How long can a standard performance improvement plan run?",
        "expected_sources": [HANDBOOK],
        "expect_contains": ["60 days"],
        "favours": "either",
        "why_hard": "One bullet among eight near-identical lines.",
    },

    # --- not in the corpus: the ONLY correct answer is "I don't know" ---
    {
        "id": "absent-bonus",
        "question": "Is there an annual bonus scheme?",
        "expected_sources": [],
        "expect_contains": [],
        "absent_terms": ["bonus"],   # must appear in NO corpus file (checked by tests/unit/test_eval_assets.py)
        "favours": "either",
        "why_hard": "The benefits file lists other perks, which tempts an invented answer.",
    },
    {
        "id": "absent-dress-code",
        "question": "What is the dress code?",
        "expected_sources": [],
        "expect_contains": [],
        "absent_terms": ["dress code"],   # must appear in NO corpus file (checked by tests/unit/test_eval_assets.py)
        "favours": "either",
        "why_hard": "The handbook has a code of conduct, which invites a confident guess.",
    },
    {
        "id": "absent-azure-subscription-id",
        "question": "What is Nexora Tech's Azure subscription ID?",
        "expected_sources": [],
        "expect_contains": [],
        "absent_terms": ["subscription id"],   # must appear in NO corpus file (checked by tests/unit/test_eval_assets.py)
        "favours": "either",
        "why_hard": "The policy talks about subscriptions and invites an invented ID. (Nexora hallucination test 12.)",
    },
    {
        "id": "absent-azure-admin-limit",
        "question": "What is the maximum number of Azure administrators allowed at Nexora Tech?",
        "expected_sources": [],
        "expect_contains": [],
        "absent_terms": ["maximum number"],   # must appear in NO corpus file (checked by tests/unit/test_eval_assets.py)
        "favours": "either",
        "why_hard": "The policy discusses administrators and least privilege but gives no number. (Nexora hallucination test 13.)",
    },
]

# Catch a copy-paste slip at import time rather than halfway through a run.
_ids = [case["id"] for case in CASES]
if len(_ids) != len(set(_ids)):
    duplicates = sorted({case_id for case_id in _ids if _ids.count(case_id) > 1})
    raise ValueError(f"Duplicate case ids in eval_set.py: {duplicates}")


def in_corpus_cases():
    """Cases with a known source document — the only ones hit-rate can be measured on."""
    return [case for case in CASES if case["expected_sources"]]


def refusal_cases():
    """Cases whose correct answer is 'I don't know' — graded on refusal, not retrieval."""
    return [case for case in CASES if not case["expected_sources"]]
