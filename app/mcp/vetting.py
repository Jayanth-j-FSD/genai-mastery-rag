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
  text          present, not enormous, free of control, zero-width, lone-surrogate, private-use and unassigned
                characters and of letters that draw nothing (the Hangul fillers), free of words that mix Latin with
                Cyrillic, Greek or Armenian letters (a Latin word with one Cyrillic letter; a word of up to three
                letters whose only foreign letters are the symbols of units is not judged, so "100µs", "kΩ" and
                "ΔT" pass), and free of instruction-like text, read across line breaks and with look-alike letters
                made plain (Week 8's sanitizer patterns, so there is one definition of "instruction-like"). The
                signals a tool-poisoning payload is made of (an order to hide it from the user, an order to act
                first, a path to a secret, a tag such as <system>) are counted over the WHOLE definition of one tool, so a payload
                split between the description and a parameter is still one payload: two different signals refuse
                the tool, and a tag such as <important> counts as two
  schema        an object with a modest number of well-named parameters and a modest total size
  read-only     optionally, only tools the server itself declares read-only (readOnlyHint)

What it cannot do: a plain-English instruction that uses none of the trigger words passes, a look-alike letter
outside the table below passes, and a harmless description that happens to use a trigger word is refused (the
operator can reword their own server, but not someone else's). A character this Python's Unicode tables do not know
yet is refused, and so is a parameter name such as `$top` or `filter[status]`. Pattern matching is a filter, not a proof.
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
_OTHER_ALPHABETS = ("CYRILLIC", "GREEK", "ARMENIAN", "CHEROKEE", "COPTIC")
_UNIT_SYMBOLS = frozenset("\u03bc\u03a9\u0394\u03c0")           # micro, ohm, delta and pi as NFKC leaves them: the symbols of "µs", "kΩ", "ΔT", "πr"
INVISIBLE_LETTERS = frozenset("\u115f\u1160\u3164\uffa0")       # the Hangul fillers: letters that draw nothing, so they can sit between words

# Look-alikes that Unicode compatibility folding does not make plain: Latin letters such as a script g, a dotless i and the
# small capitals, the commonest Cyrillic, Greek and Armenian letters drawn like Latin ones, and typographic apostrophes. A
# letter that is not in this table is not made plain. Used only to read a COPY of the text for matching; the text itself is
# never changed.
_CONFUSABLE_LETTERS = {
    "a": "\u0251\u1D00\u0430\u03B1", "b": "\u0299", "c": "\u1D04\u0441\u03F2", "d": "\u1D05\u0501", "e": "\u1D07\u0435\u03B5",
    "f": "\uA730", "g": "\u0261\u0262\u0581", "h": "\u029C\u04BB\u0570", "i": "\u0131\u026A\u0456\u03B9",
    "j": "\u1D0A\u0458\u03F3", "k": "\u1D0B\u03BA", "l": "\u029F\u04CF", "m": "\u1D0D", "n": "\u0274\u0578\u03C0",
    "o": "\u1D0F\u043E\u03BF\u0585", "p": "\u1D18\u0440\u03C1", "q": "\u051B\u0566", "r": "\u0280\u0433", "s": "\uA731\u0455",
    "t": "\u1D1B\u03C4", "u": "\u1D1C\u03C5\u057D\u03BC", "v": "\u1D20\u03BD", "w": "\u1D21\u051D", "x": "\u0445\u03C7",
    "y": "\u028F\u0443", "z": "\u1D22", "A": "\u0410\u0391\u0394", "B": "\u0412\u0392", "C": "\u0421\u03F9", "E": "\u0415\u0395",
    "H": "\u041D\u0397", "I": "\u0406\u0399", "J": "\u0408\u037F", "K": "\u041A\u039A", "M": "\u041C\u039C", "N": "\u039D",
    "O": "\u041E\u039F\u03A9", "P": "\u0420\u03A1", "Q": "\u051A", "S": "\u0405", "T": "\u0422\u03A4", "W": "\u051C",
    "X": "\u0425\u03A7", "Y": "\u03A5\u0423", "Z": "\u0396", "'": "\u2018\u2019\u02BC"}
_CONFUSABLES = {ord(look_alike): plain_letter for plain_letter, look_alikes in _CONFUSABLE_LETTERS.items() for look_alike in look_alikes}

# The signals a tool-poisoning payload is made of, beyond the Week 8 sanitizer's phrases. Each of the plain ones is common
# alone ("Before using this tool, call list_projects"; "Reads a .env file"), so ONE does not refuse a tool: it takes two
# DIFFERENT signals together, anywhere in the same definition. A tag such as <important> is not an ordinary phrase in a tool
# definition, so it counts as two and refuses alone.
_POISON_SIGNALS = {
    "a tag such as <important>": re.compile(r"<\s*/?\s*(important|secret|admin)(?![\w-])", re.I),     # a bare tag: <admin-token> is a placeholder
    "a tag such as <system>": re.compile(r"<\s*/?\s*(system|instructions?)\b", re.I),
    "an order to hide it from the user": re.compile(r"\b(do not|don't|never)\s+(tell|mention|reveal|inform|disclose|let)\b.{0,40}\b(user|human|anyone)\b", re.I),
    "an order to act before or first": re.compile(r"\b(before|prior to)\s+(using|calling|you use|you call)\s+this tool\b|\b(call|use)\s+this tool\s+(first|before)\b|\balways\s+call\s+this\s+tool\b", re.I),
    "a path to a secret": re.compile(r"~/\.|\.ssh\b|\bid_rsa\b|/etc/passwd|\.env\b|%userprofile%", re.I),     # "~/." is a dot-directory in a home folder
}
_STRONG_SIGNALS = frozenset({"a tag such as <important>"})


def _fold(text):
    """A copy of the text for matching only: compatibility forms made plain (NFKD), combining marks dropped, and the
    look-alike letters in the table above mapped to their plain letter. The table is applied before the decomposition too,
    because NFKD turns a lunate sigma into a final sigma, which no longer looks like a "c"."""
    decomposed = unicodedata.normalize("NFKD", text.translate(_CONFUSABLES))
    return "".join(char for char in decomposed if unicodedata.category(char) not in ("Mn", "Me")).translate(_CONFUSABLES)


def is_plain_name(name):
    """True for a tool name that is a plain identifier of at most 64 characters (what every provider accepts)."""
    return bool(_NAME_RE.fullmatch(name))


def _odd_character(text):
    """The first character that has no business in a tool description: a control, format (zero-width, tag), lone
    surrogate, private-use or unassigned character, or a letter that draws nothing. Line breaks (CR and LF) and tabs are
    fine, and so is a zero-width joiner inside an emoji sequence."""
    for index, char in enumerate(text):
        if char in "\r\n\t":
            continue
        if char in INVISIBLE_LETTERS:
            return char
        if unicodedata.category(char) not in ("Cc", "Cf", "Co", "Cn", "Cs"):
            continue
        if char == "\u200d" and 0 < index < len(text) - 1:
            before = text[index - 1] if unicodedata.category(text[index - 1]) != "Mn" or index < 2 else text[index - 2]
            if unicodedata.category(before) in ("So", "Sk") and unicodedata.category(text[index + 1]) == "So":
                continue
        return char
    return None


def _mixed_alphabet_word(text):
    """A word that mixes Latin letters with Cyrillic, Greek or Armenian: the look-alike trick ("ignоre" with a Cyrillic
    o). Combining marks are dropped first, so a mark cannot split a word in two. A word of up to three letters whose only
    foreign letters are the symbols of units is not judged ("µs", "kΩ", "ΔT"); any other short word is."""
    cleaned = "".join(char for char in unicodedata.normalize("NFKC", text) if unicodedata.category(char) not in ("Mn", "Me"))
    for word in re.findall(r"\w+", cleaned):
        script_of, letter_count = {}, 0
        for char in word:
            if char.isalpha():
                letter_count += 1
                try:
                    script_of[char] = unicodedata.name(char).split()[0]
                except ValueError:
                    script_of[char] = "UNKNOWN"
        scripts = set(script_of.values())
        if "LATIN" in scripts and scripts & set(_OTHER_ALPHABETS):
            foreign = {char for char, script in script_of.items() if script in _OTHER_ALPHABETS}
            if letter_count <= 3 and foreign <= _UNIT_SYMBOLS:         # digits do not count: "100µs" is a unit, "ignоre" is a word
                continue
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


def _text_problem(text, seen=None):
    """Why this text may not reach the model, or None when it may.

    `seen` is the set of poisoning signals found so far in the same tool definition: a payload split between the
    description and a parameter's description is one payload, so the signals of every string are counted together."""
    if len(text) > MAX_DESCRIPTION_CHARS:
        return f"a {len(text)}-character text (limit {MAX_DESCRIPTION_CHARS})"
    odd = _odd_character(text)
    if odd:
        return f"an unexpected character (U+{ord(odd):04X}, category {unicodedata.category(odd)})"
    word = _mixed_alphabet_word(text)
    if word:
        return f"a word that mixes alphabets ({plain(word)})"
    folded = " ".join(_fold(text).split())                  # whitespace folded and look-alikes made plain: a wrapped or disguised phrase still matches
    findings = sanitize(folded)[1]
    if findings:
        return f"instruction-like text (possible tool poisoning): {plain(findings[0], 120)}"
    found = {name for name, pattern in _POISON_SIGNALS.items() if pattern.search(folded)}
    if seen is not None:
        seen |= found
        found = seen
    if sum(2 if name in _STRONG_SIGNALS else 1 for name in found) >= 2:
        return f"text that reads like a tool-poisoning payload ({', '.join(sorted(found))})"
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
    seen = set()                                            # the poisoning signals found so far in this one definition
    problem = _text_problem(description, seen)
    if problem:
        return False, f"{server}.{name} has {problem} in its description"
    title = getattr(tool, "title", None)
    if isinstance(title, str) and title.strip():
        problem = _text_problem(title, seen)
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
        problem = _text_problem(text, seen)
        if problem:
            return False, f"{server}.{name} has {problem} in its input schema ({path})"

    if require_read_only:
        hint = getattr(getattr(tool, "annotations", None), "read_only_hint", None)
        if hint is not True:
            return False, f"{server}.{name} is not declared read-only (readOnlyHint is {hint})"
    return True, "ok"
