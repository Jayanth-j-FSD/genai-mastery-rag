"""Week 5 support — read the hand-filled worksheet files back in.

Week 5's real work is you reading traces and writing honest notes.
The scripts only move that writing around and count it. This module understands the
one file format those notes live in, so `code_notes.py` and `rank_problems.py` do not
each invent their own parser.

The format is deliberately plain markdown, so the file stays readable to a human (and
to your mentor) rather than becoming a data file you cannot skim:

    ## trace 3f9ac210

    **Question:** How many sick days do employees get?
    **Answer:** Employees get 24 days of paid leave. [source: annual-leave.md]

    - verdict: bad
    - note: it answered with the annual leave number for a question about sick days
    - severity: 3
    - code: answered-a-different-question

Each `- field: value` must sit on ONE line. A note that wraps onto a second line will
have only its first line read, which is why every script prints back what it parsed.
"""
import os
import re

# A block starts at "## trace <id>".
_BLOCK_RE = re.compile(r"^#{2,3}\s+trace\s+(\S+)\s*$", re.IGNORECASE)
# The hand-filled fields.
_FIELD_RE = re.compile(r"^\s*-\s*(verdict|note|severity|code)\s*:\s*(.*)$", re.IGNORECASE)
# Context carried over from the generated worksheet.
_QUESTION_RE = re.compile(r"^\*\*Question:\*\*\s*(.*)$", re.IGNORECASE)
_ANSWER_RE = re.compile(r"^\*\*Answer:\*\*\s*(.*)$", re.IGNORECASE)
_REFUSED_RE = re.compile(r"^\*\*Refused:\*\*\s*(.*)$", re.IGNORECASE)
# Machine-readable metadata, e.g. "<!-- sample_size: 20 -->".
_META_RE = re.compile(r"^<!--\s*([a-z_]+)\s*:\s*(.*?)\s*-->\s*$", re.IGNORECASE)

VALID_VERDICTS = ("ok", "bad")
VALID_SEVERITIES = (1, 2, 3)


def _blank_block(trace_id):
    return {
        "trace_id": trace_id,
        "question": "",
        "answer": "",
        "refused": "",
        "verdict": "",
        "note": "",
        "severity": "",
        "code": "",
    }


def parse(path):
    """Read a worksheet file. Returns (blocks, metadata).

    `blocks` is one dict per `## trace <id>` section, in file order, with whatever
    fields were filled in (empty strings where they were not). `metadata` holds any
    `<!-- key: value -->` comments found in the file.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"No worksheet at {path}")

    blocks = []
    metadata = {}
    current = None

    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.rstrip("\n")

            meta_match = _META_RE.match(line)
            if meta_match:
                metadata[meta_match.group(1).lower()] = meta_match.group(2)
                continue

            block_match = _BLOCK_RE.match(line)
            if block_match:
                current = _blank_block(block_match.group(1))
                blocks.append(current)
                continue

            if current is None:
                continue          # preamble before the first trace block

            field_match = _FIELD_RE.match(line)
            if field_match:
                current[field_match.group(1).lower()] = field_match.group(2).strip()
                continue

            for pattern, key in ((_QUESTION_RE, "question"),
                                 (_ANSWER_RE, "answer"),
                                 (_REFUSED_RE, "refused")):
                match = pattern.match(line)
                if match:
                    current[key] = match.group(1).strip()
                    break

    return blocks, metadata


def normalize_verdict(value):
    """Return "ok"/"bad", or None if it was not filled in with something recognisable."""
    cleaned = (value or "").strip().lower()
    return cleaned if cleaned in VALID_VERDICTS else None


def normalize_severity(value):
    """Return 1, 2 or 3, or None if missing or not one of those."""
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    try:
        number = int(cleaned)
    except ValueError:
        return None
    return number if number in VALID_SEVERITIES else None


def normalize_code(value):
    """A group key that tolerates spacing and capitalisation differences.

    "Wrong Document" , "wrong document" and "wrong-document" are the same group, so a
    typo in spacing does not silently split one problem into two.
    """
    cleaned = (value or "").strip().lower()
    cleaned = re.sub(r"[\s_]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned.strip("-")


def validate_notes(blocks):
    """Check the notes pass is complete. Returns a list of human-readable problems.

    An empty list means the worksheet is ready for the grouping step.
    """
    problems = []
    if not blocks:
        problems.append("No `## trace <id>` blocks found — is this the right file?")
        return problems

    for block in blocks:
        trace_id = block["trace_id"]
        verdict = normalize_verdict(block["verdict"])
        if verdict is None:
            problems.append(
                f"trace {trace_id}: verdict is {block['verdict']!r}; "
                f"it must be one of {list(VALID_VERDICTS)}")
            continue
        if verdict == "ok":
            continue              # a good answer needs no note and no severity
        if not block["note"]:
            problems.append(f"trace {trace_id}: marked bad but has no note")
        if normalize_severity(block["severity"]) is None:
            problems.append(
                f"trace {trace_id}: marked bad but severity is {block['severity']!r}; "
                f"it must be 1, 2 or 3")
    return problems


def failures(blocks):
    """Just the blocks marked bad, with severity parsed to an int."""
    result = []
    for block in blocks:
        if normalize_verdict(block["verdict"]) != "bad":
            continue
        entry = dict(block)
        entry["severity"] = normalize_severity(block["severity"])
        result.append(entry)
    return result
