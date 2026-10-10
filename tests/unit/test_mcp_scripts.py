"""Week 9: the MCP demo scripts, run for real as subprocesses (offline, no model, no key)."""
import ast
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import _testkit  # noqa: F401  (puts the project root on sys.path)
from app.agent.defense import Defense
from app.agent.loop import AgentRun
from app.config import BASE_DIR

sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
import run_agent_mcp  # noqa: E402

ENV = dict(os.environ, PYTHONWARNINGS="ignore", PYTHONIOENCODING="utf-8", ANONYMIZED_TELEMETRY="False")


def run_script(*args, timeout=120):
    return subprocess.run([sys.executable, *args], cwd=BASE_DIR, env=ENV, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


class RunAgentMcpListTests(unittest.TestCase):
    def config(self, servers):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump({"servers": servers}, handle)
        handle.close()
        self.addCleanup(os.remove, handle.name)
        return handle.name

    def test_list_shows_what_each_server_offered_and_exits_cleanly(self):
        path = self.config([{"name": "utils", "command": "python", "args": ["-m", "app.mcp.servers.utils_server"]},
                            {"name": "hris", "command": "python", "args": ["-m", "app.mcp.servers.hris_server"]}])
        result = run_script(os.path.join("scripts", "run_agent_mcp.py"), "--config", path, "--list")
        self.assertEqual(result.returncode, 0, result.stderr[-400:])
        self.assertIn("discovered 5 tool(s) on 2 server(s); 5 accepted, 0 refused", result.stdout)
        for name in ("utils.calculate", "utils.add_days", "hris.get_leave_balance", "hris.get_employee_summary"):
            self.assertIn(name, result.stdout)

    def test_adding_a_server_to_the_config_adds_its_tools_with_no_code_change(self):
        one = run_script(os.path.join("scripts", "run_agent_mcp.py"), "--list", "--config",
                         self.config([{"name": "utils", "command": "python", "args": ["-m", "app.mcp.servers.utils_server"]}]))
        two = run_script(os.path.join("scripts", "run_agent_mcp.py"), "--list", "--config",
                         self.config([{"name": "utils", "command": "python", "args": ["-m", "app.mcp.servers.utils_server"]},
                                      {"name": "hris", "command": "python", "args": ["-m", "app.mcp.servers.hris_server"]}]))
        self.assertIn("2 tool(s) on 1 server(s)", one.stdout)
        self.assertIn("5 tool(s) on 2 server(s)", two.stdout)

    def test_an_allowlist_refusal_is_reported_in_the_list(self):
        path = self.config([{"name": "hris", "command": "python", "args": ["-m", "app.mcp.servers.hris_server"],
                             "allow": ["get_leave_balance"]}])
        result = run_script(os.path.join("scripts", "run_agent_mcp.py"), "--list", "--config", path)
        self.assertIn("1 accepted, 2 refused", result.stdout)
        self.assertIn("allowlist", result.stdout)

    def test_a_missing_config_is_a_clear_error_not_a_traceback(self):
        result = run_script(os.path.join("scripts", "run_agent_mcp.py"), "--list", "--config", "no-such-file.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("could not read the MCP config", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_a_question_or_list_is_required(self):
        result = run_script(os.path.join("scripts", "run_agent_mcp.py"))
        self.assertNotEqual(result.returncode, 0)

    def test_a_step_limit_of_zero_is_refused_instead_of_quietly_becoming_the_default(self):
        result = run_script(os.path.join("scripts", "run_agent_mcp.py"), "--max-steps", "0", "a question")
        self.assertEqual(result.returncode, 1)
        self.assertIn("--max-steps must be greater than 0", result.stdout)

    def test_a_server_that_will_not_start_is_one_clear_line_naming_it_not_a_traceback(self):
        path = self.config([{"name": "broken", "command": "python", "args": ["-c", "raise SystemExit(3)"]}])
        result = run_script(os.path.join("scripts", "run_agent_mcp.py"), "--list", "--config", path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Error: the MCP server 'broken' could not be started", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_a_config_of_the_wrong_shape_is_a_clear_error(self):
        path = self.config([{"name": "a", "command": "python", "allow": "get_leave_balance"}])
        result = run_script(os.path.join("scripts", "run_agent_mcp.py"), "--list", "--config", path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("allow must be a list", result.stdout)


class RunAgentMcpAgentTests(unittest.TestCase):
    """The agent path of the script, with the servers and the model replaced (no processes, no model)."""

    def call(self, *args, provider=None):
        provider = provider or mock.MagicMock()
        provider.__enter__.return_value = provider
        provider.tools = [mock.MagicMock()]
        provider.report.return_value = ["discovered 1 tool(s)"]
        run = AgentRun(question="q", answer="14 days.", stop_reason="final", usage={"calls": 1, "prompt_tokens": 1, "completion_tokens": 1})
        out = io.StringIO()
        with (mock.patch.object(run_agent_mcp, "MCPToolProvider", return_value=provider),
              mock.patch.object(run_agent_mcp.loop, "run_agent", return_value=run) as agent,
              mock.patch.object(run_agent_mcp.pipeline, "require_index"),
              contextlib.redirect_stdout(out)):
            code = run_agent_mcp.main(list(args))
        return code, out.getvalue(), agent

    def test_defense_switches_the_week_8_layers_on_and_says_what_that_costs(self):
        code, out, agent = self.call("--defense", "a question")
        self.assertEqual(code, 0)
        self.assertIsInstance(agent.call_args.kwargs["defense"], Defense)
        self.assertIn("a final answer must cite a policy document", out)
        self.assertIn("withheld", out)

    def test_without_defense_there_is_no_note_and_no_defence(self):
        code, out, agent = self.call("a question")
        self.assertEqual(code, 0)
        self.assertIsNone(agent.call_args.kwargs["defense"])
        self.assertNotIn("--defense", out)

    def test_a_missing_index_is_reported_up_front_when_the_policy_server_is_configured(self):
        out = io.StringIO()
        with (mock.patch.object(run_agent_mcp.pipeline, "require_index", side_effect=RuntimeError("no index yet: run ingest")),
              mock.patch.object(run_agent_mcp, "MCPToolProvider") as provider,
              contextlib.redirect_stdout(out)):
            code = run_agent_mcp.main(["a question"])
        self.assertEqual(code, 1)
        self.assertIn("Error: no index yet", out.getvalue())
        provider.assert_not_called()                              # no server was started for a run that cannot work

    def test_listing_the_tools_needs_no_index(self):
        code, out, _agent = self.call("--list")
        self.assertEqual(code, 0)
        self.assertIn("discovered 1 tool(s)", out)


class RawDemoTests(unittest.TestCase):
    def test_the_raw_demo_shows_both_ways_to_open_a_conversation_then_discovery_a_call_and_an_error(self):
        result = run_script(os.path.join("scripts", "mcp_raw_demo.py"))
        self.assertEqual(result.returncode, 0, result.stderr[-400:])
        for needle in ("A. THE NEWER WAY", "B. THE OLDER WAY", '"method": "server/discover"', '"method": "initialize"',
                       "notifications/initialized", '"method": "tools/list"', '"method": "tools/call"', '"isError":true',
                       "never saw a question, a model or an agent"):
            self.assertIn(needle, result.stdout)
        self.assertEqual(result.stdout.count("3 tools discovered"), 2)                      # once per way
        self.assertEqual(result.stdout.count('"isError":true'), 2)

    def test_the_raw_demo_uses_no_mcp_library(self):
        with open(os.path.join(BASE_DIR, "scripts", "mcp_raw_demo.py"), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertFalse(imported & {"mcp", "fastmcp", "mcp_types"}, imported)
        self.assertLessEqual(imported, {"json", "os", "queue", "subprocess", "sys", "tempfile", "threading", "app"})


class OtherAgentDemoTests(unittest.TestCase):
    def test_the_other_agent_imports_nothing_from_this_project(self):
        with open(os.path.join(BASE_DIR, "scripts", "other_agent_demo.py"), encoding="utf-8") as handle:
            source = handle.read()
        imports = [line.strip() for line in source.splitlines() if line.startswith(("import ", "from "))]
        self.assertTrue(any("fastmcp" in line for line in imports))
        self.assertFalse([line for line in imports if line.split()[1].split(".")[0] in ("app", "evals", "scripts")], imports)


if __name__ == "__main__":
    unittest.main()
