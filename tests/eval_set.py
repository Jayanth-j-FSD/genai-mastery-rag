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
"""

# expected_sources: documents that legitimately answer it.
#                   An EMPTY list means "not in the corpus — the app must refuse".
# expect_contains:  a correct answer contains at least ONE of these phrases.
# favours:          prediction — "keyword", "dense", or "either".
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
        "id": "exact-code-freeze",
        "question": "What is the December code-freeze rule for booking leave?",
        "expected_sources": ["annual-leave.md"],
        "expect_contains": ["not guaranteed"],
        "favours": "keyword",
        "why_hard": "'code-freeze' is a rare compound term appearing in exactly one file.",
    },
    {
        "id": "acronym-mfa",
        "question": "Is MFA mandatory?",
        "expected_sources": ["security-policy.md"],
        "expect_contains": ["required"],
        "favours": "keyword",
        "why_hard": "The document spells out 'multi-factor authentication'; the query is the acronym.",
    },
    {
        "id": "exact-collaboration-day",
        "question": "Which day is the company-wide collaboration day?",
        "expected_sources": ["remote-work.md"],
        "expect_contains": ["tuesday"],
        "favours": "keyword",
        "why_hard": "An exact named phrase, easy to match literally.",
    },

    # --- paraphrases: where meaning-only search earns its place ---
    {
        "id": "paraphrase-usb",
        "question": "Can I copy customer data onto my own USB stick?",
        "expected_sources": ["security-policy.md"],
        "expect_contains": ["never", "must not", "not allowed", "prohibited"],
        "favours": "dense",
        "why_hard": "The policy says 'personal devices'; the question says 'USB stick'. No shared words.",
    },
    {
        "id": "paraphrase-hacked",
        "question": "Who do I tell if I think we have been hacked?",
        "expected_sources": ["security-policy.md"],
        "expect_contains": ["security@northwind.example", "1 hour"],
        "favours": "dense",
        "why_hard": "'hacked' never appears; the document says 'security incident'.",
    },
    {
        "id": "paraphrase-receipt-window",
        "question": "How long do I have to hand in a receipt after buying something?",
        "expected_sources": ["expenses.md"],
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

    # --- facts that live in TWO documents: a fair answer may cite either ---
    {
        "id": "ambiguous-home-office",
        "question": "How much can I claim for home-office equipment?",
        "expected_sources": ["expenses.md", "remote-work.md"],
        "expect_contains": ["$500", "500"],
        "favours": "either",
        "why_hard": "The $500 limit is stated in both files; either is a correct source.",
    },
    {
        "id": "ambiguous-leave-days",
        "question": "How many annual leave days do full-time employees get?",
        "expected_sources": ["annual-leave.md", "benefits.md"],
        "expect_contains": ["24"],
        "favours": "either",
        "why_hard": "24 days appears in both the leave policy and the benefits summary.",
    },

    # --- right document, but the answer has to read carefully ---
    {
        "id": "negative-carryover-payout",
        "question": "Are unused leave days beyond the carry-over limit paid out?",
        "expected_sources": ["annual-leave.md"],
        "expect_contains": ["not paid out", "not paid", "forfeited"],
        "favours": "either",
        "why_hard": "The answer is a negative statement, which models often soften or invert.",
    },
    {
        "id": "detail-december-forfeit",
        "question": "What happens to unused leave days on 31 December?",
        "expected_sources": ["annual-leave.md"],
        "expect_contains": ["forfeited"],
        "favours": "either",
        "why_hard": "Requires the specific consequence, not the general carry-over rule.",
    },

    # --- not in the corpus: the ONLY correct answer is "I don't know" ---
    {
        "id": "absent-parental-leave",
        "question": "What is the company's parental leave policy?",
        "expected_sources": [],
        "expect_contains": [],
        "favours": "either",
        "why_hard": "Nothing in the corpus covers it; answering at all is a failure.",
    },
    {
        "id": "absent-sick-days",
        "question": "How many sick days do employees get?",
        "expected_sources": [],
        "expect_contains": [],
        "favours": "either",
        "why_hard": "Adjacent to the leave policy, so it invites a confident wrong answer.",
    },
    {
        "id": "absent-notice-period",
        "question": "What is the notice period for resignation?",
        "expected_sources": [],
        "expect_contains": [],
        "favours": "either",
        "why_hard": "Sounds like an HR policy that ought to exist here, but does not.",
    },
    {
        "id": "absent-bonus",
        "question": "Is there an annual bonus scheme?",
        "expected_sources": [],
        "expect_contains": [],
        "favours": "either",
        "why_hard": "The benefits file lists other perks, which tempts an invented answer.",
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
