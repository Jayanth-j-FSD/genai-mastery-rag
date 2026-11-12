"""A small HRIS (HR information system) as an MCP server, with SYNTHETIC data (Week 9, track C).

This is a separate program that offers a few read-only "tools" over MCP. It waits on
standard input for a request such as "list your tools" or "call get_leave_balance with employee E1001" and
answers on standard output. The host decides when to ask; this server only answers.

Safety by design, so the agent can be "bolted on" without trusting it with everything:
  * Read-only: no tool changes any data.
  * Access control by scope: the default scope ("basic") offers leave and org facts only. The payroll tool
    exists only when the server is started with HRIS_SCOPE=payroll, so under the default scope an agent
    cannot even DISCOVER it, let alone call it. (Least privilege: do not offer what is not needed.)
  * Input checks: an employee id must look like E1234, and an unknown id is a recoverable error that tells
    the caller what to fix, not a crash.

Run it by hand to see it wait (it prints nothing until a client talks to it):
    python -m app.mcp.servers.hris_server
"""
import json
import os
import re
from datetime import date

os.environ.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")    # no update check: it would write a cache file outside this project

from fastmcp import FastMCP                                   # noqa: E402
from fastmcp.exceptions import ToolError                      # noqa: E402

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "hris_employees.json")
_ID_RE = re.compile(r"^E\d{4}$")
SCOPE = os.environ.get("HRIS_SCOPE", "basic").strip().lower()
if SCOPE not in ("basic", "payroll"):
    raise SystemExit(f"HRIS_SCOPE must be 'basic' or 'payroll', got {SCOPE!r}")

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}

mcp = FastMCP(
    "hris",
    instructions=("Read-only access to a SYNTHETIC HR information system: leave balances, an employee summary and "
                  "direct reports. Employee ids look like E1001."))


def _load():
    with open(DATA_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _employee(employee_id):
    """The record for an id, or a ToolError that says what to fix."""
    if not isinstance(employee_id, str) or not _ID_RE.match(employee_id.strip()):
        raise ToolError("employee_id must look like E1001 (the letter E and four digits).")
    data = _load()
    record = data["employees"].get(employee_id.strip())
    if record is None:
        raise ToolError(f"no employee {employee_id.strip()!r}. Known ids look like {sorted(data['employees'])[0]} to {sorted(data['employees'])[-1]}.")
    return employee_id.strip(), record, data


@mcp.tool(annotations=READ_ONLY)
def get_leave_balance(employee_id: str) -> dict:
    """Annual leave entitlement, days taken and days remaining, and sick days taken, for one employee.

    Use it when a question is about THIS employee's own leave (how many days they have left). For what the
    company policy allows, search the policy documents instead. Employee ids look like E1001.
    """
    employee_id, record, data = _employee(employee_id)
    leave = record["leave"]
    return {"employee_id": employee_id, "as_of": data["as_of"],
            "annual_entitlement_days": leave["annual_entitlement"], "annual_taken_days": leave["annual_taken"],
            "annual_remaining_days": leave["annual_entitlement"] - leave["annual_taken"],
            "sick_taken_days": leave["sick_taken"]}


@mcp.tool(annotations=READ_ONLY)
def get_employee_summary(employee_id: str) -> dict:
    """Name, department, manager, start date and employment status (probation or permanent) of one employee.

    Use it to learn whether someone is still on probation and when probation ends. Employee ids look like E1001.
    """
    employee_id, record, data = _employee(employee_id)
    days = (date.fromisoformat(data["as_of"]) - date.fromisoformat(record["start_date"])).days
    return {"employee_id": employee_id, "name": record["name"], "department": record["department"],
            "manager_id": record["manager_id"], "start_date": record["start_date"], "days_of_service": days,
            "employment_status": record["status"], "probation_end": record["probation_end"], "as_of": data["as_of"]}


@mcp.tool(annotations=READ_ONLY)
def list_direct_reports(manager_id: str) -> dict:
    """The employee ids and names of the people who report directly to one manager. Manager ids look like E1000."""
    manager_id, _record, data = _employee(manager_id)
    reports = [{"employee_id": key, "name": value["name"]} for key, value in sorted(data["employees"].items())
               if value["manager_id"] == manager_id]
    return {"manager_id": manager_id, "direct_reports": reports}


if SCOPE == "payroll":
    @mcp.tool(annotations=READ_ONLY)
    def get_salary_band(employee_id: str) -> dict:
        """The salary band (not the salary) of one employee. Offered only when the server runs with the payroll scope."""
        employee_id, record, _data = _employee(employee_id)
        return {"employee_id": employee_id, "salary_band": record["salary_band"]}


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False, log_level="WARNING")
