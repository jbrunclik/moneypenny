"""A deterministic safety net under the grounding verifier: prices and sites.

The verifier (a small model) lists most claims but now and then skips one -
a used-price range in parentheses, a row of a table, a second-hand portal
(honesty probe, Oct 4 2026). Two kinds of specifics can be checked
mechanically, and become not_found claims unless the verifier already
covered them or the sentence says they are unverified:
- a price (a number or range with Kč / CZK / EUR / €) whose numbers appear
  on no page read this turn;
- a linked or named site (a markdown link, or a bare domain like
  cyklobazar.cz) whose domain is not among the pages read this turn.
"""

import re
from urllib.parse import urlparse

from src.agent.grounding_annotations import ClaimVerdict
from src.agent.source_pages import SourcePage

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
SITE_REASON = "This site is not among the pages read this turn."
_LINK = re.compile(r"\[([^\]\n]{1,80})\]\((https?://[^)\s]+)\)")
_DOMAIN = re.compile(
    r"(?<![\w@/.-])((?:[a-z0-9-]+\.)+(?:cz|sk|com|eu|de|at|pl|org|net|shop|store|co\.uk))(?![\w.-]*\w)",
    re.IGNORECASE,
)


def _digits(number: str) -> str:
    return re.sub(r"\D", "", number)


def _numbers(text: str) -> set[str]:
    return {_digits(n) for n in _NUMBER.findall(text)}


def _sentence(answer: str, start: int, end: int) -> str:
    left = max(answer.rfind(mark, 0, start) for mark in (". ", "! ", "? ", "\n"))
    rights = [i for i in (answer.find(mark, end) for mark in (". ", "! ", "? ", "\n")) if i != -1]
    return answer[left + 1 : min(rights) if rights else len(answer)]


def _site(host_or_url: str) -> str:
    """Registered domain, lower case, without www (shop.cz for https://www.shop.cz/x)."""
    host = urlparse(host_or_url).hostname or host_or_url
    labels = host.lower().removeprefix("www.").split(".")
    return ".".join(labels[-3:] if host.lower().endswith(".co.uk") else labels[-2:])


def _covered(text: str, claims: list[ClaimVerdict]) -> bool:
    folded = text.casefold()
    return any(folded in c.quote.casefold() or c.quote.casefold() in folded for c in claims)


def missed_sites(
    answer: str, pages: list[SourcePage], claims: list[ClaimVerdict]
) -> list[ClaimVerdict]:
    """not_found claims for linked or named sites the turn never read."""
    read = {_site(p.url) for p in pages}
    found: list[tuple[int, int, str, str]] = []  # start, end, quote, site
    for link in _LINK.finditer(answer):
        found.append((link.start(), link.end(), link.group(1).strip(), _site(link.group(2))))
    for domain in _DOMAIN.finditer(answer):
        if not any(start <= domain.start() < end for start, end, _q, _s in found):
            found.append((domain.start(), domain.end(), domain.group(1), _site(domain.group(1))))
    missed: list[ClaimVerdict] = []
    seen: set[str] = set()
    for start, end, quote, site in sorted(found):
        if site in read or site in seen or _covered(quote, claims):
            continue
        if _UNVERIFIED.search(_sentence(answer, start, end)):
            continue
        seen.add(site)
        missed.append(ClaimVerdict(quote=quote, verdict="not_found", reason=SITE_REASON))
    return missed


def missed_specifics(
    answer: str, sources: str, pages: list[SourcePage], claims: list[ClaimVerdict]
) -> list[ClaimVerdict]:
    """Prices and sites the verifier left unlisted that no page read backs."""
    return missed_prices(answer, sources, claims) + missed_sites(answer, pages, claims)


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
