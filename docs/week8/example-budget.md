# Week 8: the call budget, one question, one model, before and after

This is an illustration of the mechanism on the failure the survey found. It is **one run each, on one
question, on one model**, so it shows how the budget behaves and proves nothing about how often it helps. The
measured comparison is described in `CHANGES.md` and has its own numbers.

The question is the unanswerable one (`t7-unanswerable`: no document mentions a manager's bonus limit). The model
is `gemini-3.7-flash`, not the model the measured comparison uses: the lite models the earlier runs used had stopped
answering when this was recorded (see `CHANGES.md`), and this model had a few requests left. The two runs were copied
from the terminal and no JSON was saved, so their figures cannot be re-derived from the repository. The evidence is
the saved pair of runs described in `CHANGES.md`, not this page.

## Before: no budget

Raw output of `python scripts/run_agent.py --model gemini-3.7-flash "What is the maximum bonus a manager can approve for a team member?"`
(the run was recorded before the Week 7 review fixes were merged, so its first lines differ slightly from today's printer).

```
Question: What is the maximum bonus a manager can approve for a team member?

[step 1] CALL   search_policies({"query": "maximum bonus manager approve", "top_k": 5})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company may pe...
          (713 tokens, 6.6s)
[step 2] CALL   search_policies({"top_k": 5, "query": "bonus"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] # Northstar Digital Solutions Pvt. Ltd. � Synthetic HR Policy Handbook **Document purpose:** Synthetic test data for RAG applications. **Version:** 2026.1 **Effectiv...
          (1317 tokens, 67.1s)
[step 3] CALL   search_policies({"top_k": 5, "query": "Compensation and Payroll"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] ## 7. Compensation and Payroll ### Salary Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. ...
          (1961 tokens, 1.8s)
[step 4] CALL   search_policies({"top_k": 5, "query": "discretionary bonus"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company may pe...
          (1948 tokens, 2.1s)
[step 5] CALL   search_policies({"top_k": 5, "query": "Variable Pay"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] ### Variable Pay Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to eli...
          (2094 tokens, 1.6s)
[step 6] CALL   search_policies({"top_k": 6, "query": "Variable Pay Northstar"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] ### Variable Pay Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to eli...
          (2234 tokens, 1.8s)
[step 7] CALL   search_policies({"query": "Variable Pay payout", "top_k": 5})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] ### Variable Pay Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. The policy applies to eli...
          (2238 tokens, 2.3s)
[step 8] CALL   search_policies({"top_k": 5, "query": "Variable Pay bonus percent"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] ## 7. Compensation and Payroll ### Salary Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. ...
          (2397 tokens, 86.7s)

NO ANSWER: the run was stopped before a final answer.

stopped because: max_steps | 8 step(s), 8 tool call(s) | 8 model call(s), 14902 tokens, 81.5s in the model, 170.4s total
```

Eight searches with eight different wordings, then the step limit. No answer.

## After: at most 3 calls per tool

Raw output of the same command with `AGENT_MAX_CALLS_PER_TOOL=3` in the environment.

```
Question: What is the maximum bonus a manager can approve for a team member?
Model: gemini-3.7-flash

[step 1] CALL   search_policies({"query": "manager approve bonus team member"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company may pe...
          (708 tokens, 3.3s)
[step 2] CALL   search_policies({"top_k": 6, "query": "bonus"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] # Northstar Digital Solutions Pvt. Ltd. � Synthetic HR Policy Handbook **Document purpose:** Synthetic test data for RAG applications. **Version:** 2026.1 **Effectiv...
          (1057 tokens, 1.4s)
[step 3] CALL   search_policies({"top_k": 6, "query": "Compensation and Payroll"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] ## 7. Compensation and Payroll ### Salary Northstar Digital Solutions Pvt. Ltd. maintains this policy to provide consistent expectations for employees and managers. ...
          (1848 tokens, 2.5s)
[step 4] CALL   search_policies({"top_k": 6, "query": "Variable Pay Northstar"})  <-- BLOCKED by the argument guard, the tool never ran
          RESULT BUDGET: search_policies has already run 3 times for this question. Use what you found. If it is not enough, reply exactly: I don't know based on the provided documents.
          (2172 tokens, 1.9s)
[step 5] FINAL ANSWER  (1576 tokens, 3.2s)

ANSWER:
I don't know based on the provided documents.

stopped because: final | 5 step(s), 4 tool call(s) | 5 model call(s), 7361 tokens, 12.4s in the model, 12.7s total
```

Three searches ran. The fourth was not executed: the loop answered it with the `BUDGET` text shown on the line
below it, and the model's next step was the refusal sentence.

Two things to read carefully:

- The marker on step 4 says "BLOCKED by the argument guard". That wording was wrong: it was the budget, as the
  RESULT line shows. The printer now says "refused before it ran (the result says by what)" and has a test.
- The tokens fell from 14,902 to 7,361 and the calls from 8 to 5, and the run ended with an answer instead of
  the step limit. One run each cannot say how typical that is. The model could equally have ignored the notice and
  asked again (the prediction allows for that), and a second identical run could differ.
