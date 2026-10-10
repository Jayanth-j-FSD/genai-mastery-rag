# Week 7: a real agent run, step by step

Raw output of `python scripts/run_agent.py` on 2026-10-11 with the model `gemini-3.5-flash-lite`, copied as printed. Nothing was edited. Each [step] line is one thing the agent did: which tool the model chose, with what arguments, what the tool returned, and what the step cost.

Command: `python scripts/run_agent.py "A permanent employee's written resignation is received by People Operations on 3 November 2026. On what date does the notice period end?"`

```
Question: A permanent employee's written resignation is received by People Operations on 3 November 2026. On what date does the notice period end?

[step 1] CALL   search_policies({"query": "notice period permanent employee"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company may pe...
          (724 tokens, 1.4s)
[step 2] CALL   add_days({"days": 30, "date": "2026-11-03"})
          RESULT 2026-12-03 (Thursday)
          (1256 tokens, 0.7s)
[step 3] CALL   add_days({"days": 60, "date": "2026-11-03"})
          RESULT 2027-01-02 (Saturday)
          (1312 tokens, 0.9s)
[step 4] CALL   search_policies({"query": "notice period resignation permanent"})
          RESULT [1] [source: Acme-Employment-Terms-2026.md] # ACME EMPLOYMENT TERMS POLICY 2026 Effective date: 2026-03-01 ## 1. Scope This policy applies to regular full-time Acme employees. A separate written agreement may provide a ...
          (908 tokens, 0.7s)
[step 5] CALL   remember({"fact": "Acme-Employment-Terms-2026.md requires 30 calendar days of written notice for permanent employees."})
          RESULT Saved note 1.
          (1319 tokens, 1.0s)
[step 6] FINAL ANSWER  (1648 tokens, 1.2s)

ANSWER:
Based on the company policy documents, the notice period ends on **3 December 2026**.

**Key details and calculations used:**
* **Resignation receipt date:** 3 November 2026 [source: Acme-Employment-Terms-2026.md].
* **Notice period requirement:** A permanent employee must provide 30 calendar days of written notice, which begins on the date People Operations receives the written resignation [source: Acme-Employment-Terms-2026.md]. *(Note: Synthetic_HR_Policy_RAG_Test_Dat
* **End date calculation:** Adding 30 calendar days to 3 November 2026 results in **3 December 2026** (Thursday) [source: Acme-Employment-Terms-2026.md].

**Sources relied upon:**
* Acme-Employment-Terms-2026.md
* Synthetic_HR_Policy_RAG_Test_Dataset.md

stopped because: final | 6 step(s), 5 tool call(s) | 6 model call(s), 7167 tokens, 6.0s in the model, 6.9s total
notes the agent saved: Acme-Employment-Terms-2026.md requires 30 calendar days of written notice for permanent employees.
```
