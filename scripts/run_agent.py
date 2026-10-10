"""Week 7, mentor checks #1 and #2: run the agent on one question and WATCH it work.

This prints every step as it happens, so nothing the agent does is hidden: which tool it
chose, what arguments it sent, what the tool returned, and how many tokens that step cost. It ends with
the final answer and why the run stopped. If you ask for something unanswerable, or turn the limits
down, you can watch the stop conditions work.

Run:
    python scripts/run_agent.py "I will have 25 unused leave days. How many carry forward?"
    python scripts/run_agent.py --workflow "How many weeks of paid parental leave are there?"   # the fixed recipe instead
    python scripts/run_agent.py --max-steps 2 "..."          # watch it stop on the step limit
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openai                                              # noqa: E402
from app import llm                                        # noqa: E402
from app.agent import display, loop, workflow              # noqa: E402
from app.agent.tools import default_tools                  # noqa: E402
from app.config import settings                            # noqa: E402
from app.console import make_output_safe                   # noqa: E402
from app.rag import pipeline                               # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the HR agent (or the fixed workflow) on one question.")
    parser.add_argument("question", nargs="+", help="the question to ask")
    parser.add_argument("--workflow", action="store_true", help="run the fixed workflow instead of the agent")
    parser.add_argument("--max-steps", type=int, default=None, help=f"step limit (default {settings.agent_max_steps})")
    parser.add_argument("--max-tokens", type=int, default=None, help=f"total token budget (default {settings.agent_max_total_tokens})")
    parser.add_argument("--timeout", type=float, default=None, help=f"seconds before giving up (default {settings.agent_timeout_seconds})")
    parser.add_argument("--no-memory", action="store_true", help="turn off the notes and the shortening of old results")
    parser.add_argument("--model", default=None, help="chat model for this run (default LLM_MODEL)")
    args = parser.parse_args(argv)
    make_output_safe()
    for flag, value in (("--max-steps", args.max_steps), ("--max-tokens", args.max_tokens), ("--timeout", args.timeout)):
        if value is not None and value <= 0:             # 0 would silently fall back to the default
            print(f"Error: {flag} must be greater than 0, got {value}.")
            return 1
    question = " ".join(args.question)

    try:
        pipeline.require_index()
        print(f"Question: {question}\nModel: {args.model or settings.llm_model}\n")
        if args.workflow:
            run = workflow.run_workflow(question, model=args.model, on_step=display.show_step)
        else:
            run = loop.run_agent(question, default_tools(), max_steps=args.max_steps, max_total_tokens=args.max_tokens,
                                 timeout_seconds=args.timeout, use_memory=not args.no_memory, model=args.model,
                                 on_step=display.show_step)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1
    except openai.APIError as exc:
        print(f"Error: the AI provider call failed ({type(exc).__name__}): {exc}")
        return 1

    print()
    print("ANSWER:" if run.finished else "NO ANSWER: the run was stopped before a final answer.")
    if run.answer:
        print(run.answer)
    usage = run.usage
    print(f"\nstopped because: {run.stop_reason} | {len(run.steps)} step(s), "
          f"{sum(len(s['tool_calls']) for s in run.steps)} tool call(s) | "
          f"{usage.get('calls', 0)} model call(s), {usage.get('prompt_tokens', 0) + usage.get('completion_tokens', 0)} tokens, "
          f"{usage.get('api_seconds', 0):.1f}s in the model, {run.elapsed_seconds:.1f}s total")
    if run.notes:
        print("notes the agent saved: " + " | ".join(run.notes))
    return 0 if run.finished else 2


if __name__ == "__main__":
    sys.exit(main())
