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


def test_conflicting_verdicts_on_a_repeated_quote_are_dropped() -> None:
    # "800 Kč" stands under both agencies: which occurrence a verdict meant is
    # unknowable, so a conflicting pair is dropped rather than mislabelled
    anns = validate_claims(
        [
            _claim(quote="800 Kč", verdict="not_found", reason="PřepiServis v nich není."),
            _claim(quote="800 Kč", source=2, source_quote="poplatek 800 Kč"),
        ],
        _ANSWER,
        _PAGES,
    )

    assert anns == []


def test_agreeing_verdicts_on_a_repeated_quote_mark_the_first_occurrence() -> None:
    # A business named twice is the same claim wherever it stands
    [ann] = validate_claims(
        [_claim(quote="800 Kč", verdict="not_found"), _claim(quote="800 Kč", verdict="not_found")],
        _ANSWER,
        _PAGES,
    )

    assert ann["prefix"].endswith("1 590 Kč + ")


def test_a_quote_copied_without_markdown_still_matches() -> None:
    # LLMs often drop the ** of the source; the prefix still comes from the answer
    [ann] = validate_claims(
        [_claim(quote="PřepiServis: rychlost 24–48 hodin", verdict="not_found")],
        _ANSWER,
        _PAGES,
    )

    assert ann["quote"] == "PřepiServis: rychlost 24–48 hodin"
    assert ann["prefix"].endswith("+ 800 Kč.\n**")


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


@pytest.mark.parametrize("passage", ["", "   ", "\n"])
def test_blank_passage_is_not_a_citation(passage: str) -> None:
    [ann] = validate_claims(
        [_claim(quote="cena 1 590 Kč", source=1, source_quote=passage)], _ANSWER, _PAGES
    )

    assert ann["verdict"] == "not_found"
    assert "source_quote" not in ann


def test_downgraded_claim_drops_the_reason_of_its_old_verdict() -> None:
    # "the speed is missing" describes a partial claim, not one the sources lack
    [ann] = validate_claims(
        [
            _claim(
                quote="cena 1 590 Kč",
                verdict="partial",
                source=1,
                source_quote="paraphrase that is not in the page",
                reason="Rychlost ve zdroji chybí.",
            )
        ],
        _ANSWER,
        _PAGES,
    )

    assert ann["verdict"] == "not_found"
    assert "reason" not in ann


def test_prefix_offsets_survive_characters_that_casefold_longer() -> None:
    # "ß".casefold() == "ss": the prefix must still be sliced from the answer
    answer = "Weißbier Straße ab 5 €: Bar Alfa."
    [ann] = validate_claims([_claim(quote="Bar Alfa", verdict="not_found")], answer, [])

    assert ann["prefix"].endswith("5 €: ")


def test_a_long_claim_is_shortened_not_dropped() -> None:
    """A not_found claim over the quote cap used to vanish - an unmarked shop
    in the honesty probe (Oct 4 2026)."""
    answer = (
        "* **Physical Stores:** They have dedicated showrooms and service centers in "
        "**Prague** (Karlín and others), **Brno**, and **Hradec Králové**."
    )
    quote = (
        "Physical Stores: They have dedicated showrooms and service centers in Prague "
        "(Karlín and others), Brno, and Hradec Králové"
    )
    [ann] = validate_claims([_claim(verdict="not_found", quote=quote, reason="r")], answer, [])

    assert ann["verdict"] == "not_found"
    assert len(ann["quote"]) <= Config.GROUNDING_CHECK_MAX_QUOTE_CHARS
    assert ann["quote"].startswith("Physical Stores")


def test_a_claim_across_list_items_keeps_its_first_line() -> None:
    answer = "Prodejny:\n* **Brno**\n* **Hradec Králové**"
    [ann] = validate_claims(
        [_claim(verdict="not_found", quote="Brno\n  * **Hradec Králové**", reason="r")], answer, []
    )

    assert ann["quote"] == "Brno"
