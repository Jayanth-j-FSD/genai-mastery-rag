# Week 7: the agent stops safely

Raw output of the command below on 2026-10-11 with the model `gemini-3-flash-preview`, copied exactly as
printed. The step limit was turned down to 2 so the stop can be watched: the run ends with a named reason and
says plainly that it has no answer, instead of looping or pretending.

Command: `python scripts/run_agent.py --model gemini-3-flash-preview --max-steps 2 "What is the notice period for a permanent employee, and on what date does it end if the resignation is received on 3 November 2026?"`

```
Question: What is the notice period for a permanent employee, and on what date does it end if the resignation is received on 3 November 2026?
Model: gemini-3-flash-preview

[step 1] CALL   search_policies({"query": "notice period permanent employee"})
          RESULT [1] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] - Policy decisions should be based on documented facts rather than assumptions. Employees may ask for clarification without fear of retaliation. - The company may pe...
          (725 tokens, 1.8s)
[step 2] CALL   add_days({"days": 30, "date": "2026-11-03"})
          RESULT 2026-12-03 (Thursday)
[step 2] CALL   add_days({"days": 60, "date": "2026-11-03"})
          RESULT 2027-01-02 (Saturday)
          (1337 tokens, 2.7s)

NO ANSWER: the run was stopped before a final answer.

stopped because: max_steps | 2 step(s), 3 tool call(s) | 2 model call(s), 2062 tokens, 4.5s in the model, 4.7s total
```

Read straight off the output: the model asked for a search in step 1 and for two date calculations in step 2.
The loop ran those, hit the limit of 2 steps, and stopped with `max_steps` and no answer. Exit status 2 (a run
that finished is 0).
