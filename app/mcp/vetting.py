"""Check a tool before the agent trusts it (Week 9: "keeping it safe").

When an agent connects to a server somebody else wrote, the server tells the agent what its
tools are called, what they do, and what arguments they take. The agent's model reads those descriptions
and believes them. So a description is an INPUT THE ATTACKER CAN WRITE: "tool poisoning" is a description
that contains instructions to the model ("before you answer, also call ...") rather than a plain
explanation. This module looks at each discovered tool BEFORE it reaches the agent and refuses the ones that
fail a few plain checks. It is a gate, not a guarantee: a server you do not trust should not be connected
at all, and a tool that passes can still return poisoned RESULTS, which is what Week 8's output screening
(`app/agent/defense.py`) is for.

The model reads the whole definition, not only the top-level description, so every piece of text in it is
checked: the description, the title, and every string inside the input schema (a parameter's description,
title, default, enum values and examples).

The checks, each a plain rule a reviewer can disagree with:
  allowlist     if the operator listed the tools they expect from a server, anything else is refused
  name          letters, digits, underscore and hyphen only, not absurdly long, and not a name the agent loop
                reserves for itself ("remember")
  text          present, not enormous, free of control, zero-width, private-use and unassigned characters, free
                of words that mix alphabets (a Latin word with one Cyrillic letter), and free of
                instruction-like text, read across line breaks (Week 8's sanitizer patterns, so there is one
                definition of "instruction-like")
  schema        an object with a modest number of well-named parameters and a modest total size
  read-only     optionally, only tools the server itself declares read-only (readOnlyHint)

What it cannot do: a plain-English instruction that uses none of the sanitizer's trigger words passes, and a
harmless description that happens to use one is refused (the operator can reword their own server, but not
someone else's). Pattern matching is a filter, not a proof.
"""
import json
import re
import unicodedata

from app.agent.defense import sanitize

_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")           # used with fullmatch: a "$" would let a trailing newline through
_KEY_RE = re.compile(r"[A-Za-z0-9_$@:.-]{1,64}")                # schema keys: property names and JSON-schema keywords
MAX_DESCRIPTION_CHARS = 1200
MAX_SCHEMA_CHARS = 8000
MAX_PARAMETERS = 12
RESERVED_NAMES = frozenset({"remember"})                        # the agent loop adds its memory tool under this name


def is_plain_name(name):
    """True for a tool name that is a plain identifier of at most 64 characters (what every provider accepts)."""
    return bool(_NAME_RE.fullmatch(name))


def _odd_character(text):
    """The first character that has no business in a tool description: a control, format (zero-width, tag),
    private-use or unassigned character. Newlines and tabs are fine."""
    for char in text:
        if char not in "\n\t" and unicodedata.category(char) in ("Cc", "Cf", "Co", "Cn"):
            return char
    return None


def _mixed_alphabet_word(text):
    """A word that mixes Latin letters with another alphabet: the look-alike trick ("ignоre" with a Cyrillic o)."""
    for word in re.findall(r"\w+", text):
        scripts = set()
        for char in word:
            if char.isalpha():
                try:
                    scripts.add(unicodedata.name(char).split()[0])
                except ValueError:
                    scripts.add("UNKNOWN")
        if "LATIN" in scripts and len(scripts) > 1:
            return word
    return None


def plain(text, limit=60):
    """Text from a tool definition as it is safe to print: printable ASCII only and short. A line break or tab becomes
    a space (so a server cannot forge a line of a report), any other control or non-ASCII character is escaped."""
    shown = []
    for char in str(text):
        if char in (chr(13), chr(10), chr(9)):
            shown.append(" ")
        elif 32 <= ord(char) < 127:
            shown.append(char)
        elif ord(char) < 256:
            shown.append(chr(92) + "x" + format(ord(char), "02x"))
        else:
            shown.append(char.encode("unicode_escape").decode("ascii"))
    shown = "".join(shown)
    return shown if len(shown) <= limit else shown[:limit - 3] + "..."


def _text_problem(text):
    """Why this text may not reach the model, or None when it may."""
    if len(text) > MAX_DESCRIPTION_CHARS:
        return f"a {len(text)}-character text (limit {MAX_DESCRIPTION_CHARS})"
    odd = _odd_character(text)
    if odd:
        return f"an unexpected character (U+{ord(odd):04X}, category {unicodedata.category(odd)})"
    word = _mixed_alphabet_word(text)
    if word:
        return f"a word that mixes alphabets ({plain(word)})"
    findings = sanitize(" ".join(text.split()))[1]            # whitespace folded, so a phrase wrapped over a line still matches
    if findings:
        return f"instruction-like text (possible tool poisoning): {plain(findings[0], 120)}"
    return None


def _strings(value, path):
    """Every string inside a JSON-like value with where it sits. A key that is not an acceptable name is
    reported as (path, None)."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            if not _KEY_RE.fullmatch(str(key)):
                yield f"{path}.{str(key)[:30]}", None
            else:
                yield from _strings(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _strings(item, f"{path}[{index}]")


def vet_tool(server, tool, allow=None, require_read_only=False):
    """Return (True, "ok") if the tool may be given to the agent, otherwise (False, why not).

    `tool` is whatever the MCP client returned: it needs .name, .description, .input_schema, and
    optionally .title and .annotations with a read_only_hint.
    """
    name = getattr(tool, "name", "") or ""
    if allow is not None and name not in allow:
        return False, f"{server}.{name or '?'} is not on the allowlist for this server"
    if not _NAME_RE.fullmatch(name):
        return False, f"{server}: the tool name {name!r} is not a plain identifier"
    if name in RESERVED_NAMES:
        return False, f"{server}.{name} has a name the agent reserves for its own tool"

    description = getattr(tool, "description", "") or ""
    if not description.strip():
        return False, f"{server}.{name} has no description, so the model could not choose it sensibly"
    if len(description) > MAX_DESCRIPTION_CHARS:
        return False, f"{server}.{name} has a {len(description)}-character description (limit {MAX_DESCRIPTION_CHARS})"
    problem = _text_problem(description)
    if problem:
        return False, f"{server}.{name} has {problem} in its description"
    title = getattr(tool, "title", None)
    if isinstance(title, str) and title.strip():
        problem = _text_problem(title)
        if problem:
            return False, f"{server}.{name} has {problem} in its title"

    schema = getattr(tool, "input_schema", None) or {}
    if not isinstance(schema, dict) or schema.get("type", "object") != "object":
        return False, f"{server}.{name} does not take an object of named arguments"
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict) or len(properties) > MAX_PARAMETERS:
        return False, f"{server}.{name} declares more than {MAX_PARAMETERS} parameters"
    bad = [key for key in properties if not _NAME_RE.fullmatch(str(key))]
    if bad:
        return False, f"{server}.{name} has oddly named parameter(s): {bad}"
    if len(json.dumps(schema, default=str)) > MAX_SCHEMA_CHARS:
        return False, f"{server}.{name} has an input schema over {MAX_SCHEMA_CHARS} characters"
    for path, text in _strings(schema, "schema"):
        if text is None:
            return False, f"{server}.{name} has an oddly named key in its schema ({path})"
        problem = _text_problem(text)
        if problem:
            return False, f"{server}.{name} has {problem} in its input schema ({path})"

    if require_read_only:
        hint = getattr(getattr(tool, "annotations", None), "read_only_hint", None)
        if hint is not True:
            return False, f"{server}.{name} is not declared read-only (readOnlyHint is {hint})"
    return True, "ok"
