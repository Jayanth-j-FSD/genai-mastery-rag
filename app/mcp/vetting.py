"""Check a tool before you trust it (Week 9: "keeping it safe").

When an agent connects to a server somebody else wrote, the server tells the agent what its
tools are called, what they do, and what arguments they take. The agent's model reads those descriptions
and believes them. So a description is an INPUT THE ATTACKER CAN WRITE: "tool poisoning" is a description
that contains instructions to the model ("before you answer, also call ...") rather than a plain
explanation. This module looks at each discovered tool BEFORE it reaches the agent and refuses the ones that
fail a few plain checks. It is a gate, not a guarantee: a server you do not trust should not be connected
at all, and a tool that passes can still return poisoned RESULTS, which is what Week 8's output screening
(`app/agent/defense.py`) is for.

The checks, each a plain rule a reviewer can disagree with:
  allowlist     if the operator listed the tools they expect from a server, anything else is refused
  name          letters, digits, underscore and hyphen only, and not absurdly long
  description   present, not enormous (a huge one is context-stuffing), and free of instruction-like text
  schema        an object with a modest number of well-named parameters
  read-only     optionally, only tools the server itself declares read-only (readOnlyHint)
"""
import re

from app.agent.defense import sanitize

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
MAX_DESCRIPTION_CHARS = 1200
MAX_PARAMETERS = 12


def vet_tool(server, tool, allow=None, require_read_only=False):
    """Return (True, "ok") if the tool may be given to the agent, otherwise (False, why not).

    `tool` is whatever the MCP client returned: it needs .name, .description, .input_schema, and
    optionally .annotations with a read_only_hint.
    """
    name = getattr(tool, "name", "") or ""
    if allow is not None and name not in allow:
        return False, f"{server}.{name or '?'} is not on the allowlist for this server"
    if not _NAME_RE.match(name):
        return False, f"{server}: the tool name {name!r} is not a plain identifier"

    description = getattr(tool, "description", "") or ""
    if not description.strip():
        return False, f"{server}.{name} has no description, so the model could not choose it sensibly"
    if len(description) > MAX_DESCRIPTION_CHARS:
        return False, f"{server}.{name} has a {len(description)}-character description (limit {MAX_DESCRIPTION_CHARS})"
    findings = sanitize(description)[1]
    if findings:
        return False, f"{server}.{name} has instruction-like text in its description (possible tool poisoning): {findings[0]}"

    schema = getattr(tool, "input_schema", None) or {}
    if not isinstance(schema, dict) or schema.get("type", "object") != "object":
        return False, f"{server}.{name} does not take an object of named arguments"
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict) or len(properties) > MAX_PARAMETERS:
        return False, f"{server}.{name} declares more than {MAX_PARAMETERS} parameters"
    bad = [key for key in properties if not _NAME_RE.match(str(key))]
    if bad:
        return False, f"{server}.{name} has oddly named parameter(s): {bad}"

    if require_read_only:
        hint = getattr(getattr(tool, "annotations", None), "read_only_hint", None)
        if hint is not True:
            return False, f"{server}.{name} is not declared read-only (readOnlyHint is {hint})"
    return True, "ok"
