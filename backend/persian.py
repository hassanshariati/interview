"""Persian language policy for job interview questions.

Provider output is untrusted. Validate the rendered interview question rather
than assuming that a language instruction alone will be obeyed.
"""
import re

_PERSIAN_LETTERS = re.compile(r"[\u0621-\u064A\u067E\u0686\u0698\u06A9\u06AF\u06CC]")
_LATIN_LETTERS = re.compile(r"[A-Za-z]")


def is_persian_question(text: str) -> bool:
    """Allow Latin technical names but reject predominantly English questions."""
    if not isinstance(text, str):
        return False
    persian = len(_PERSIAN_LETTERS.findall(text))
    latin = len(_LATIN_LETTERS.findall(text))
    return persian >= 16 and persian >= latin * 0.65


PERSIAN_QUESTION_RULE = (
    "MANDATORY OUTPUT LANGUAGE: Write the entire answer in natural Persian "
    "(فارسی، با خط فارسی). This includes greetings, interview questions, "
    "explanations and follow-up questions, irrespective of the CV's or "
    "candidate's language. English is prohibited except for short "
    "technical product names and abbreviations (e.g. Kubernetes, API, SQL). "
    "Do not translate technical terms unnaturally. "
    "If the candidate answers in English, respond in Persian anyway. "
    "Return exactly ONE practical, concise question, with no English introduction."
)
