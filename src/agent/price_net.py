"""A deterministic safety net under the grounding verifier: prices.

The verifier (a small model) lists most claims but now and then skips one -
a used-price range in parentheses, a row of a table (honesty probe, Oct 4
2026). Prices are the easiest specifics to check mechanically: every price
in the answer (a number or range with Kč / CZK / EUR / €) whose numbers
appear on no page read this turn becomes a not_found claim, unless the
verifier already covered it or the sentence says it is unverified.
"""

import re

from src.agent.grounding_annotations import ClaimVerdict

_NUM = r"\d{1,3}(?:[   .,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_RANGE = rf"(?:{_NUM})(?:\s?[–-]\s?€?\s?(?:{_NUM}))?"
_PRICE = re.compile(
    rf"(?<![\w.,])(?:€\s?{_RANGE}|{_RANGE}\s?(?:Kč|CZK|EUR|€)(?![\w]))",
)
_NUMBER = re.compile(_NUM)
_UNVERIFIED = re.compile(
    r"neověřen|nepodařilo (?:se )?ověřit|neověřil|unverified|not verified|could not (?:be )?(?:verif|confirm)",
    re.IGNORECASE,
)
REASON = "This price is not on the pages read this turn."


def _digits(number: str) -> str:
    return re.sub(r"\D", "", number)


def _numbers(text: str) -> set[str]:
    return {_digits(n) for n in _NUMBER.findall(text)}


def _sentence(answer: str, start: int, end: int) -> str:
    left = max(answer.rfind(mark, 0, start) for mark in (". ", "! ", "? ", "\n"))
    rights = [i for i in (answer.find(mark, end) for mark in (". ", "! ", "? ", "\n")) if i != -1]
    return answer[left + 1 : min(rights) if rights else len(answer)]


def missed_prices(answer: str, sources: str, claims: list[ClaimVerdict]) -> list[ClaimVerdict]:
    """not_found claims for prices no page backs and the verifier did not list."""
    on_pages = _numbers(sources)
    covered = {_digits(n) for claim in claims for n in _NUMBER.findall(claim.quote)}
    missed: list[ClaimVerdict] = []
    for match in _PRICE.finditer(answer):
        numbers = [_digits(n) for n in _NUMBER.findall(match.group())]
        if not numbers or all(n in covered for n in numbers):
            continue
        if all(n in on_pages for n in numbers):
            continue
        if _UNVERIFIED.search(_sentence(answer, match.start(), match.end())):
            continue
        missed.append(ClaimVerdict(quote=match.group().strip(), verdict="not_found", reason=REASON))
    return missed
