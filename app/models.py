"""The shapes of a request and a response (used by the API and the pipeline).

A Pydantic model is like a typed form — it lists exactly which
fields exist and what type each is, and checks the data automatically.
"""
from typing import Literal, Optional

from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str                 # what the user asks
    # Week 4: optionally force one search strategy for this request, which makes it
    # possible to demonstrate both side by side. Omit it to use the configured mode.
    # An unknown value is rejected by the API with a 422 instead of searching wrongly.
    mode: Optional[Literal["dense", "hybrid"]] = None


class Source(BaseModel):
    document: str                 # which file the answer came from
    score: float                  # how close the match was (higher = closer)


class AskResponse(BaseModel):
    answer: str                   # the answer text
    sources: list[Source]         # the documents it used (mentor check #2)
    grounded: bool                # False when it answered "I don't know" (check #3)
    retrieval_mode: str           # which search produced this answer (Week 4)
