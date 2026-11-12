"""The agent's tool plumbing and its two pure tools: no heavy imports, so a tiny server can offer them.

A `Tool` is a function plus a description the model reads. This file holds that wrapper, the
error type a tool raises when the model made a fixable mistake, and the two tools that need nothing from the
rest of the app: exact arithmetic and exact date arithmetic. They live apart from `search_policies`
(app/agent/tools.py), which needs the vector index, so that a small MCP server (Week 9) can offer them
without loading the retriever.

Three rules every tool follows:
  1. Read-only. Nothing a tool does changes any data, so a confused or tricked model cannot do harm.
  2. Recoverable errors. A bad argument raises ToolError with a message that tells the model what to fix.
  3. A description that says WHEN to use the tool and when not to. The model picks tools from these alone.
"""
import ast
import datetime
import math
import operator
from dataclasses import dataclass
from typing import Callable


class ToolError(Exception):
    """A mistake the model can fix. The message is shown to it, so write it as advice."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict            # JSON schema of the arguments
    function: Callable          # called with the parsed arguments as keyword arguments

    def spec(self):
        """The OpenAI-style tool definition sent to the model."""
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


# ---------------------------------------------------------------------------- calculate

_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
           ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_MAX_EXPONENT = 100
_MAX_LENGTH = 200
_MAX_BITS = 5000                 # an integer result beyond this is refused, so a chain of powers cannot burn CPU


def _evaluate(node):
    """Walk the parsed expression, allowing only numbers, + - * / // % ** and parentheses."""
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_evaluate(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
            raise ToolError(f"exponent too large (limit {_MAX_EXPONENT}).")
        value = _BINARY[type(node.op)](left, right)
        if isinstance(value, complex):              # a negative base to a fractional power; % and // would then fail
            raise ToolError("that has no real-number result.")
        if isinstance(value, int) and value.bit_length() > _MAX_BITS:
            raise ToolError("the result is too large.")
        return value
    raise ToolError("only numbers and + - * / // % ** with parentheses are allowed, for example (14 - 10) * 2.")


def calculate(expression):
    """Evaluate plain arithmetic exactly. Never uses eval(): the expression is parsed and checked first."""
    if not isinstance(expression, str) or not expression.strip():
        raise ToolError("expression must be a non-empty string such as '14 - 10'.")
    if len(expression) > _MAX_LENGTH:
        raise ToolError(f"expression too long (limit {_MAX_LENGTH} characters).")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError:
        raise ToolError("could not read that as arithmetic. Use digits and + - * / ( ), for example '30 / 365'.")
    try:
        value = _evaluate(tree)
    except ZeroDivisionError:
        raise ToolError("division by zero.")
    except OverflowError:
        raise ToolError("the result is too large.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ToolError("the result is not a finite number.")
    return str(round(value, 6) if isinstance(value, float) else value)


# ---------------------------------------------------------------------------- add_days

def add_days(date, days):
    """Add a number of calendar days to a date (negative to go back). Returns the date and its weekday."""
    if not isinstance(date, str):
        raise ToolError("date must be a string in YYYY-MM-DD form, for example 2026-11-03.")
    try:
        start = datetime.date.fromisoformat(date.strip())
    except ValueError:
        raise ToolError(f"{date!r} is not a valid date. Use YYYY-MM-DD, for example 2026-11-03.")
    try:
        if isinstance(days, bool) or (isinstance(days, float) and not days.is_integer()):    # 2.9 is not 2, and nan/inf are not whole
            raise ValueError(days)
        days = int(days)
    except (TypeError, ValueError, OverflowError):
        raise ToolError("days must be a whole number of calendar days.")
    if abs(days) > 36500:
        raise ToolError("days is out of range (limit 100 years).")
    try:
        result = start + datetime.timedelta(days=days)
    except OverflowError:
        raise ToolError("that date is out of range.")
    return f"{result.isoformat()} ({result.strftime('%A')})"


# ---------------------------------------------------------------------------- the two pure tools as Tool objects

CALCULATE_DESCRIPTION = (
    "Do exact arithmetic. Use it whenever the answer needs a sum, difference, product, ratio, minimum or "
    "proration, instead of working it out in your head. Only numbers and + - * / // % ** with parentheses.")
ADD_DAYS_DESCRIPTION = (
    "Add calendar days to a date (negative days go backwards) and get the resulting date and weekday. Use it "
    "for notice periods, deadlines and leave end dates. Never count days on a calendar yourself.")


def calculator_tool():
    return Tool("calculate", CALCULATE_DESCRIPTION,
                {"type": "object", "properties": {
                    "expression": {"type": "string", "description": "for example '14 - 10' or '18 * 3 / 12'"}},
                 "required": ["expression"]},
                calculate)


def date_tool():
    return Tool("add_days", ADD_DAYS_DESCRIPTION,
                {"type": "object", "properties": {
                    "date": {"type": "string", "description": "start date as YYYY-MM-DD"},
                    "days": {"type": "integer", "description": "calendar days to add"}},
                 "required": ["date", "days"]},
                add_days)
