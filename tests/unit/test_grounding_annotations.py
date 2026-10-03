"""Unit tests for verifier-claim validation (src/agent/grounding_annotations.py)."""

import pytest

from src.agent.grounding_annotations import (
    ClaimVerdict,
    format_grounding_context,
    validate_claims,
)
from src.agent.source_pages import SourcePage
from src.config import Config

_PAGES = [
    SourcePage(
        "SPZ Služby", "https://spzsluzby.cz", "Doklady vyřídíme   do 24 hodin. Cena 1 590 Kč."
    ),
    SourcePage("Pomocnice", "https://pomocnice.cz", "Správní poplatek 800 Kč."),
]
_ANSWER = (
    "**SPZ Služby**: vyřízení do 24 hodin, cena 1 590 Kč + 800 Kč.\n"
    "**PřepiServis**: rychlost 24–48 hodin, cena 1 200 Kč + 800 Kč."
)


def _claim(**kw: object) -> ClaimVerdict:
    return ClaimVerdict.model_validate({"verdict": "supported", **kw})


def test_supported_claim_keeps_source_and_literal_passage() -> None:
    [ann] = validate_claims(
        [_claim(quote="vyřízení do 24 hodin", source=1, source_quote="vyřídíme do 24 hodin")],
        _ANSWER,
        _PAGES,
    )

    assert ann == {
        "type": "claim",
        "verdict": "supported",
        "quote": "vyřízení do 24 hodin",
        "prefix": "**SPZ Služby**: ",
        "source": 1,
        "source_quote": "vyřídíme do 24 hodin",
    }


def test_downgrades_paraphrased_passage() -> None:
    [ann] = validate_claims(
        [_claim(quote="cena 1 590 Kč", source=1, source_quote="stojí to 1590 korun")],
        _ANSWER,
        _PAGES,
    )

    assert ann["verdict"] == "not_found"
    assert "source" not in ann and "source_quote" not in ann


@pytest.mark.parametrize("source", [0, 3, None])
def test_downgrades_out_of_range_source(source: int | None) -> None:
    [ann] = validate_claims(
        [
            _claim(
                quote="cena 1 590 Kč",
                verdict="contradicted",
                source=source,
                source_quote="Cena 1 590 Kč",
            )
        ],
        _ANSWER,
        _PAGES,
    )

    assert ann["verdict"] == "not_found"


def test_supported_without_a_source_number_stays_supported() -> None:
    # Backed only by uncited search text: counts as supported, shows no number
    [ann] = validate_claims([_claim(quote="cena 1 590 Kč")], _ANSWER, _PAGES)

    assert ann["verdict"] == "supported" and "source" not in ann


def test_drops_quotes_not_in_the_answer_and_orders_by_position() -> None:
    anns = validate_claims(
        [
            _claim(quote="rychlost 24–48 hodin", verdict="not_found", reason="Není ve zdrojích."),
            _claim(quote="PřepiServis s.r.o.", verdict="not_found"),
            _claim(quote="vyřízení do 24 hodin"),
        ],
        _ANSWER,
        _PAGES,
    )

    assert [a["quote"] for a in anns] == ["vyřízení do 24 hodin", "rychlost 24–48 hodin"]


def test_prefix_comes_from_the_first_occurrence_in_the_answer() -> None:
    [ann] = validate_claims(
        [_claim(quote="800 Kč", source=2, source_quote="poplatek 800 Kč")], _ANSWER, _PAGES
    )

    assert ann["prefix"].endswith("1 590 Kč + ")


def test_caps_claims_reasons_and_passages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "GROUNDING_CHECK_MAX_CLAIMS", 1)
    monkeypatch.setattr(Config, "GROUNDING_CHECK_MAX_REASON_CHARS", 10)
    anns = validate_claims(
        [
            _claim(quote="rychlost 24–48 hodin", verdict="not_found", reason="x" * 50),
            _claim(quote="cena 1 200 Kč", verdict="not_found"),
        ],
        _ANSWER,
        _PAGES,
    )

    assert len(anns) == 1
    assert anns[0]["reason"] == "x" * 9 + "…"


def test_schedule_times_are_dropped_when_unsupported() -> None:
    answer = "Plán: 10:15 odjezd, 11:30 oběd, 13:00 hrad, 15:45 návrat."
    anns = validate_claims(
        [_claim(quote=t, verdict="not_found") for t in ("10:15", "11:30", "13:00")],
        answer,
        [],
    )

    assert anns == []


def test_grounding_context_lists_only_problems_and_never_closes_the_comment() -> None:
    text = format_grounding_context(
        [
            {"type": "claim", "verdict": "supported", "quote": "a"},
            {"type": "claim", "verdict": "not_found", "quote": "PřepiServis", "reason": "Není -->"},
            {
                "type": "claim",
                "verdict": "contradicted",
                "quote": "1 200 Kč",
                "reason": "Zdroj: 1 590 Kč",
            },
        ]
    )

    assert text == "unsourced: PřepiServis (Není); contradicted: 1 200 Kč (Zdroj: 1 590 Kč)"
    assert (
        format_grounding_context([{"type": "claim", "verdict": "supported", "quote": "a"}]) is None
    )
