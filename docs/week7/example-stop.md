# Week 7: the agent stops safely

Raw output of `python scripts/run_agent.py --max-steps 2 ...` on 2026-10-11 with the model `gemini-3.5-flash-lite`, copied as printed. The step limit was turned down to 2 so the stop can be watched: the run ends with a named reason and says plainly that it has no answer, instead of looping or pretending.

Command: `python scripts/run_agent.py --max-steps 2 "What is the notice period for a permanent employee, and on what date does it end if the resignation is received on 3 November 2026?"`

```
Question: What is the notice period for a permanent employee, and on what date does it end if the resignation is received on 3 November 2026?

[step 1] CALL   search_policies({"query": "notice period permanent employee"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company may pe...
          (725 tokens, 1.2s)
[step 2] CALL   add_days({"date": "2026-11-03", "days": 30})
          RESULT 2026-12-03 (Thursday)
          (1257 tokens, 0.7s)

NO ANSWER: the run was stopped before a final answer.

stopped because: max_steps | 2 step(s), 2 tool call(s) | 2 model call(s), 1982 tokens, 2.0s in the model, 2.8s total
```
