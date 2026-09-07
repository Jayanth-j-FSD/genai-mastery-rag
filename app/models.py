"""The shapes of a request and a response (used by the API and the pipeline).

A Pydantic model is like a typed form — it lists exactly which
fields exist and what type each is, and checks the data automatically.
"""
from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str                 # what the user asks


class Source(BaseModel):
    document: str                 # which file the answer came from
    score: float                  # how close the match was (higher = closer)


class AskResponse(BaseModel):
    answer: str                   # the answer text
    sources: list[Source]         # the documents it used (mentor check #2)
    grounded: bool                # False when it answered "I don't know" (check #3)
