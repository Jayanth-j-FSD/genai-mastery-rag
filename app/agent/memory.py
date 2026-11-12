"""Agent memory: what the agent keeps in view across a longer task.

A model has no memory between calls. It only knows what is in the messages we send. In a
long task those messages grow with every tool result, which costs tokens and buries the facts that
matter. Two simple tools against that, both deliberately small:

  Short-term memory is the conversation itself, with OLD tool results shortened to one line once more than
  the two newest results sit behind them. A result the model has not read yet is never shortened. It has
  already read the older ones; it can search again if it needs more.
  Notes are facts the agent chooses to keep with the `remember` tool ("carry-forward limit is 10 days").
  They are re-shown in the system prompt on every step, so they never scroll out of view.

Long-term memory (remembering across separate conversations, for example with a vector store or a library
such as mem0) is out of scope for this week; it is recorded as deferred in docs/week7/CHANGES.md.
"""
from app.agent.tools import Tool, ToolError

_KEEP_RECENT_RESULTS = 2        # tool results this recent are kept in full
_SHORTENED_CHARS = 140
_MAX_NOTES = 12
_MAX_NOTE_CHARS = 300


class Memory:
    def __init__(self):
        self.notes = []

    def remember(self, fact):
        """Save one short fact to keep in view."""
        if not isinstance(fact, str) or not fact.strip():
            raise ToolError("fact must be a short non-empty sentence.")
        if len(self.notes) >= _MAX_NOTES:
            raise ToolError(f"you already saved {_MAX_NOTES} notes; use what you have.")
        self.notes.append(fact.strip()[:_MAX_NOTE_CHARS])
        return f"Saved note {len(self.notes)}."

    def render(self):
        """The notes as a block appended to the system prompt ("" when there are none)."""
        if not self.notes:
            return ""
        return "\n\nNotes you saved (all still true):\n" + "\n".join(f"- {note}" for note in self.notes)

    def tool(self):
        return Tool("remember",
                    "Save one short fact you will need again, such as a limit or a number you looked up, so it stays "
                    "in front of you for the rest of the task. Use it sparingly: only for facts the final answer depends on.",
                    {"type": "object", "properties": {"fact": {"type": "string", "description": "one short sentence"}},
                     "required": ["fact"]},
                    self.remember)

    @staticmethod
    def compact(messages):
        """Shorten tool results older than the most recent few, in place. The assistant turns stay as they are.

        The results that follow the newest assistant turn are the ones the model is about to read for the first
        time, so they all stay whole even when one turn asked for more tools than _KEEP_RECENT_RESULTS.
        """
        positions = [i for i, message in enumerate(messages) if message.get("role") == "tool"]
        last_assistant = max((i for i, message in enumerate(messages) if message.get("role") == "assistant"), default=-1)
        unread = sum(1 for i in positions if i > last_assistant)
        keep = max(_KEEP_RECENT_RESULTS, unread)
        for index in positions[:max(len(positions) - keep, 0)]:
            content = messages[index]["content"]
            if len(content) > _SHORTENED_CHARS and not content.startswith("[shortened]"):
                messages[index]["content"] = "[shortened] " + " ".join(content.split())[:_SHORTENED_CHARS] + "..."
