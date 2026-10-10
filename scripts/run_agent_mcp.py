"""Week 9, mentor checks #1 and #2: the agent uses tools it DISCOVERED over MCP.

In Week 7 every tool was wired into the agent by hand. Here the agent code is exactly the same
(app/agent/loop.py is untouched), but its tools are not listed anywhere in it. This script reads a config file
of MCP servers (default: mcp_servers.json), starts each one, asks it "what tools do you have?", checks each
answer, and hands the survivors to the same agent loop.

To give the agent a new capability, add a server to the config file. Nothing in the agent changes.
Try it: delete the "hris" entry from mcp_servers.json, ask a question about an employee, and watch the agent
say it cannot; put the entry back and ask again.

Run:
    python scripts/run_agent_mcp.py --list
    python scripts/run_agent_mcp.py "Employee E1001 asks how many annual leave days they have left, and how many of those they could carry forward at year end"
    python scripts/run_agent_mcp.py --config my_servers.json --require-read-only --defense "..."
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openai                                              # noqa: E402
from app import llm                                        # noqa: E402
from app.agent import display, loop                        # noqa: E402
from app.agent.defense import Defense, trusted_contacts_from   # noqa: E402
from app.config import BASE_DIR, settings                  # noqa: E402
from app.console import make_output_safe                   # noqa: E402
from app.mcp.client import MCPToolProvider, load_specs     # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the agent with tools discovered over MCP.")
    parser.add_argument("question", nargs="*", help="the question to ask")
    parser.add_argument("--config", default=os.path.join(BASE_DIR, "mcp_servers.json"), help="MCP server config file")
    parser.add_argument("--list", action="store_true", help="connect, show what was discovered, and stop")
    parser.add_argument("--require-read-only", action="store_true", help="refuse tools the server does not declare read-only")
    parser.add_argument("--defense", action="store_true", help="also screen tool results and the final answer (Week 8)")
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--model", default=None, help="chat model for this run (default LLM_MODEL)")
    args = parser.parse_args(argv)
    make_output_safe()
    if not args.list and not args.question:
        parser.error("give a question, or use --list")

    try:
        specs = load_specs(args.config)
    except (OSError, ValueError) as exc:
        print(f"Error: could not read the MCP config {args.config!r}: {exc}")
        return 1
    try:
        with MCPToolProvider(specs, require_read_only=args.require_read_only) as provider:
            print("\n".join(provider.report()))
            if args.list:
                return 0
            if not provider.tools:
                print("\nNo usable tools were discovered, so there is nothing for the agent to do.")
                return 1
            question = " ".join(args.question)
            print(f"\nQuestion: {question}\n")
            defense = Defense(trusted_contacts=trusted_contacts_from(settings.corpus_dir),
                              system_prompt=loop.SYSTEM_PROMPT) if args.defense else None
            run = loop.run_agent(question, provider.tools, max_steps=args.max_steps, model=args.model,
                                 defense=defense, on_step=display.show_step)
    except (RuntimeError, OSError) as exc:
        print(f"Error: {exc}")
        return 1
    except openai.APIError as exc:
        print(f"Error: the AI provider call failed ({type(exc).__name__}): {exc}")
        return 1
    except llm.QuotaExhausted as exc:
        print(f"Stopped: {exc}")
        return 1

    print()
    print("ANSWER:" if run.finished else "NO ANSWER: the run was stopped before a final answer.")
    if run.answer:
        print(run.answer)
    usage = run.usage
    print(f"\nstopped because: {run.stop_reason} | {len(run.steps)} step(s) | {usage.get('calls', 0)} model call(s), "
          f"{usage.get('prompt_tokens', 0) + usage.get('completion_tokens', 0)} tokens")
    return 0 if run.finished else 2


if __name__ == "__main__":
    sys.exit(main())
