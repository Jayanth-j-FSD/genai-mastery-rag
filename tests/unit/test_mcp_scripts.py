"""Week 9: the MCP demo scripts, run for real as subprocesses (offline, no model, no key)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import _testkit  # noqa: F401  (puts the project root on sys.path)
from app.config import BASE_DIR

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


class RawDemoTests(unittest.TestCase):
    def test_the_raw_demo_shows_the_handshake_discovery_a_call_and_a_recoverable_error(self):
        result = run_script(os.path.join("scripts", "mcp_raw_demo.py"))
        self.assertEqual(result.returncode, 0, result.stderr[-400:])
        for needle in ("1. HANDSHAKE", "2. READY", "3. DISCOVERY", "4. A TOOL CALL", "5. A RECOVERABLE ERROR",
                       '"method": "initialize"', '"method": "tools/list"', '"method": "tools/call"',
                       "3 tools discovered", '"isError":true', "never saw a question, a model or an agent"):
            self.assertIn(needle, result.stdout)

    def test_the_raw_demo_uses_no_mcp_library(self):
        with open(os.path.join(BASE_DIR, "scripts", "mcp_raw_demo.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("import mcp", source)
        self.assertNotIn("fastmcp", source.replace("hris_server", ""))


class OtherAgentDemoTests(unittest.TestCase):
    def test_the_other_agent_imports_nothing_from_this_project(self):
        with open(os.path.join(BASE_DIR, "scripts", "other_agent_demo.py"), encoding="utf-8") as handle:
            source = handle.read()
        imports = [line.strip() for line in source.splitlines() if line.startswith(("import ", "from "))]
        self.assertTrue(any("fastmcp" in line for line in imports))
        self.assertFalse([line for line in imports if line.split()[1].split(".")[0] in ("app", "evals", "scripts")], imports)


if __name__ == "__main__":
    unittest.main()
