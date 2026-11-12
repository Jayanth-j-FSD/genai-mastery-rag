# Week 7: a real agent run, step by step

Raw output of the command below on 2026-10-11 with the model `gemini-3.5-flash`, copied exactly as printed:
nothing was edited, shortened or reordered. Each `[step]` line is one thing the agent did: which tool the
model chose, with what arguments, what the tool returned, and what the step cost. The printer shows only the
first 220 characters of each tool result; the model was shown the whole result (up to three passages, each cut
at 700 characters), and every step's full text is kept in the run record. A step's seconds are wall-clock
and include any wait for the free tier's rate limit; the closing line separates the time spent inside model calls.

Command: `python scripts/run_agent.py --model gemini-3.5-flash "A permanent employee's written resignation is received by People Operations on 3 November 2026. On what date does the notice period end?"`

```
Question: A permanent employee's written resignation is received by People Operations on 3 November 2026. On what date does the notice period end?
Model: gemini-3.5-flash

[step 1] CALL   search_policies({"query": "notice period permanent employee resignation"})
          RESULT [1] [source: Acme-Employment-Terms-2026.md] # ACME EMPLOYMENT TERMS POLICY 2026 Effective date: 2026-03-01 ## 1. Scope This policy applies to regular full-time Acme employees. A separate written agreement may provide a ...
          (725 tokens, 2.1s)
[step 2] CALL   search_policies({"query": "notice period permanent employee"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company may pe...
          (1203 tokens, 2.5s)
[step 3] CALL   add_days({"date": "2026-11-03", "days": 30})
          RESULT 2026-12-03 (Thursday)
          (1906 tokens, 4.1s)
[step 4] CALL   search_policies({"query": "notice period begins on the date"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company may pe...
          (2259 tokens, 1.7s)
[step 5] CALL   add_days({"days": 60, "date": "2026-11-03"})
          RESULT 2027-01-02 (Saturday)
          (2285 tokens, 1.4s)
[step 6] CALL   search_policies({"query": "notice period"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company may pe...
          (2357 tokens, 2.3s)
[step 7] FINAL ANSWER  (2870 tokens, 76.7s)

ANSWER:
The policy documents disagree on the notice period duration for permanent/confirmed employees:

### Disagreement Between Documents
1. **Acme Employment Terms Policy 2026** [source: Acme-Employment-Terms-2026.md]
   * **Notice Period:** Permanent employees (after probation) must provide **30 calendar days** of written notice.
   * **Calculation:** Adding 30 calendar days to the receipt date of **3 November 2026** sets the notice period end date as **3 December 2026** (or **2 December 2026** if counting 3 November 2026 as Day 1 of 30).

2. **Synthetic HR Policy RAG Test Dataset** [source: Synthetic_HR_Policy_RAG_Test_Dataset.md]
   * **Notice Period:** Confirmed (permanent) employees must provide **60 calendar days** of notice.
   * **Calculation:** Adding 60 calendar days to the receipt date of **3 November 2026** sets the notice period end date as **2 January 2027** (or **1 January 2027** if counting 3 November 2026 as Day 1 of 60).

### Key Numbers Used
* **Resignation Receipt Date:** 3 November 2026
* **Notice Duration Option 1:** 30 calendar days
* **Notice Duration Option 2:** 60 calendar days

stopped because: final | 7 step(s), 6 tool call(s) | 7 model call(s), 13605 tokens, 21.0s in the model, 91.0s total
```

What the run shows, read straight off the output above:

- Six tool calls, in an order the model chose: `search_policies`, `search_policies`, `add_days`,
  `search_policies`, `add_days`, `search_policies`, then a final answer. It did not use `remember`.
- Every tool result was sent back to the model before its next call, and the two date calculations happened
  between searches, not after all of them.
- The answer reports that the two documents disagree (30 days in the Acme terms, 60 in the handbook) and gives
  an end date for each, with citations. It does not choose between them.
- It took 7 model calls and 13,605 tokens for one question. The last step's 76.7 seconds is wall-clock time
  (waiting included); the whole run spent 21.0 seconds inside model calls.

This is one run on one model, not a typical one: the same question on another model can take a different
number of steps and give a different answer.
