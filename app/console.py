"""Small helpers that keep the command-line scripts from crashing on Windows.

A model answer can contain characters like an arrow or a curly quote. Some
Windows consoles (Git Bash with Python's default cp1252 encoding, for example) cannot show
them, and `print()` then crashes the whole script with UnicodeEncodeError, after the answer
has already been paid for. This switches the error handling to "show a ? instead", so the
script always finishes. It does not change the encoding, only what happens on a bad character.
"""
import os
import sys


def make_output_safe() -> None:
    """Call once at the start of a script that prints model text."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass          # not a normal text stream (for example under a test runner): leave it


def display_path(path, base) -> str:
    """A short path for messages: relative to `base` when possible, otherwise as given.

    os.path.relpath raises ValueError on Windows when the two paths are on different drives
    (a --out on C: while the project lives on D:), and a message is not worth crashing for.
    """
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return str(path)
