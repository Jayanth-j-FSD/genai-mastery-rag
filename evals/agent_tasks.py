"""The tasks the agent and the fixed workflow are raced on (Week 7), and later graded on their path (Week 8).

A race is only fair if both runners get the same questions and the same definition of
"got it right". These tasks use the same fields as the Week 6 eval cases (`expected_sources`,
`expect_contains`, `expect_all`, `should_refuse`), so the same rule checks (`evals/checks.py`) score them.
Every expected fact below was read out of the named documents and is verified by
`tests/unit/test_agent_tasks.py` against the real corpus.

`expected_tools` is what a sensible run would call, in order of need. Week 7 does not grade it; Week 8
does (trajectory evaluation: did the agent take the right steps, not only reach the right answer?).

`source_facts` are the document sentences the answer is built from; a unit test proves each is still in an
expected document, so a task cannot go stale silently.

`why` says what the task is built to expose. The mix is deliberate: some tasks need only one lookup (a
fixed workflow should win those), some need exact dates or sums (where a model working in its head is
risky), some need two documents, and one cannot be answered at all (the agent must stop safely and say so).
"""
ACME_LEAVE = "Acme-Leave-Policy-2026.md"
ACME_TERMS = "Acme-Employment-Terms-2026.md"
REMOTE = "Northstar-Remote-Work-Policy-2026.md"
NEXORA = "Nexora_Tech_Azure_Cloud_Data_Access_Policy.md"
HANDBOOK = "Synthetic_HR_Policy_RAG_Test_Dataset.md"

TASKS = [
    {"id": "t7-single-lookup",
     "source_facts": ["16 weeks of paid parental leave"],
     "question": "How many weeks of paid parental leave are available?",
     "expected_sources": [ACME_LEAVE], "expect_contains": [], "expect_all": ["16 weeks"], "should_refuse": False,
     "expected_tools": ["search_policies"],
     "why": "One lookup, no arithmetic: the fixed workflow should do this as well and far more cheaply."},
    {"id": "t7-carry-forward-sum",
     "source_facts": ["carry forward up to 10 unused annual-leave days"],
     "question": "I will have 25 unused annual leave days at the end of the year. How many can I carry forward, and how many are above the limit?",
     "expected_sources": [ACME_LEAVE], "expect_contains": [], "expect_all": ["10", "15"], "should_refuse": False,
     "expected_tools": ["search_policies", "calculate"],
     "why": "A lookup (the limit) followed by a subtraction the model should not do in its head."},
    {"id": "t7-notice-end-date",
     "source_facts": ["30 calendar days of written notice", "the notice period begins on the date people operations receives the written resignation"],
     "question": "Under the Acme employment terms, a permanent employee's written resignation is received by People Operations on 3 November 2026. On what date does the notice period end?",
     "expected_sources": [ACME_TERMS],
     "expect_contains": ["3 december", "december 3", "2026-12-03", "2 december", "december 2", "2026-12-02"], "expect_all": [],
     "should_refuse": False, "expected_tools": ["search_policies", "add_days"],
     "why": "30 calendar days from a given date: date arithmetic is where language models slip. Either 2 or 3 December is accepted, because the policy does not say whether the first day counts."},
    {"id": "t7-leave-end-date",
     "source_facts": ["carry forward up to 10 unused annual-leave days"],
     "question": "Under the Acme leave policy I carry forward the maximum allowed number of unused days into next year. If I take all of those carried-forward days as consecutive calendar days, counting 4 January 2027 as the first day, what is my last day of leave?",
     "expected_sources": [ACME_LEAVE], "expect_contains": ["13 january", "january 13", "2027-01-13"], "expect_all": [],
     "should_refuse": False, "expected_tools": ["search_policies", "add_days"],
     "why": "Look up the limit (10), then count 10 days starting on the 4th: the last day is the 13th, and an off-by-one gives the 14th."},
    {"id": "t7-remote-eligibility",
     "source_facts": ["after completing 60 days of service", "up to three days per week"],
     "question": "An employee joined 45 days ago. Can they request remote work yet? If not, after how many days of service can they, and what is the most days a week they could then work remotely?",
     "expected_sources": [REMOTE], "expect_contains": ["three days", "3 days"], "expect_all": ["60"], "should_refuse": False,
     "expected_tools": ["search_policies", "calculate"],
     "why": "A condition to check (45 against 60 days) and a second fact (the weekly limit) from the same policy."},
    {"id": "t7-two-documents",
     "source_facts": ["7 calendar days of written notice", "12 paid sick-leave days"],
     "question": "Under the Acme terms, how many days of written notice must an employee on probation give, and under the Acme leave policy how many paid sick leave days are there per year?",
     "expected_sources": [ACME_TERMS, ACME_LEAVE], "expect_contains": [], "expect_all": ["7", "12"], "should_refuse": False,
     "expected_tools": ["search_policies", "search_policies"],
     "why": "Two facts in two different documents: a single retrieval may fetch only one of them."},
    {"id": "t7-conflict",
     "source_facts": ["employees receive 18 days of annual leave", "24 days of annual leave per calendar year"],
     "question": "How many days of annual leave does an employee get each year?",
     "expected_sources": [ACME_LEAVE, HANDBOOK], "expect_contains": [], "expect_all": ["18", "24"], "should_refuse": False,
     "expected_tools": ["search_policies"],
     "why": "The documents disagree (18 in the Acme policy, 24 in the handbook). A good answer reports both."},
    {"id": "t7-cloud-two-sections",
     "source_facts": ["only the permissions required", "approved secrets-management solution such as azure key vault"],
     "question": "A developer only needs to read files from one Azure Storage container. Should they get access to the whole subscription, and where must any access keys they use be stored?",
     "expected_sources": [NEXORA], "expect_contains": [], "expect_all": ["key vault"], "should_refuse": False,
     "expected_tools": ["search_policies", "search_policies"],
     "why": "Two sections of one policy: least privilege, and where secrets live."},
    {"id": "t7-unanswerable",
     "absent_terms": ["bonus"],
     "question": "What is the maximum bonus a manager can approve for a team member?",
     "expected_sources": [], "expect_contains": [], "expect_all": [], "should_refuse": True,
     "expected_tools": ["search_policies"],
     "why": "Not in any document. The agent must search, find nothing, and stop with 'I don't know' instead of looping."},
]

# The question whose answer is the same in every document, for a quick smoke run of the agent.
SMOKE_QUESTION = TASKS[0]["question"]


def get_tasks(only=None):
    """All tasks, or just the ids given. Unknown ids are an error."""
    if not only:
        return [dict(task) for task in TASKS]
    wanted = set(only)
    unknown = wanted - {task["id"] for task in TASKS}
    if unknown:
        raise ValueError(f"unknown task id(s): {sorted(unknown)}")
    return [dict(task) for task in TASKS if task["id"] in wanted]
