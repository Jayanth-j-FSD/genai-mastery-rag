"""The question bank (tests/trace_questions.txt) as a list, and a seeded sample of it (Week 11).

Week 5 wrote about a hundred questions to build a population of requests. The cost scripts reuse it as stand-in
traffic, because the 41 eval questions are all hard on purpose and real traffic is mostly easy. A sample is drawn with a
seed, so the same seed gives the same questions and a before-and-after run asks the same ones.
"""
import os
import random

from app.config import BASE_DIR

DEFAULT_PATH = os.path.join(BASE_DIR, "tests", "trace_questions.txt")


def load_questions(path=None):
    """The questions in a file, one per line, in order. Blank lines and lines starting with # are ignored, and so is a repeat."""
    questions, seen = [], set()
    with open(path or DEFAULT_PATH, encoding="utf-8") as handle:
        for line in handle:
            question = line.strip()
            if question and not question.startswith("#") and question.lower() not in seen:
                seen.add(question.lower())
                questions.append(question)
    return questions


def sample(questions, count, seed, exclude=()):
    """`count` questions picked with a seeded shuffle, so the same seed picks the same ones; fewer if there are not enough.

    `exclude` is questions to leave out (the eval questions, so nothing is counted twice), compared ignoring case."""
    left_out = {question.lower() for question in exclude}
    pool = [question for question in questions if question.lower() not in left_out]
    return random.Random(seed).sample(pool, min(max(count, 0), len(pool)))
