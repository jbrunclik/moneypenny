"""The grounding verifier's deterministic net (src/agent/specifics_net.py).

The net adds not_found claims for prices and sites the verifier skipped.
A false flag puts a wrong "unverified" mark on a correct answer; a miss lets
an invented price or shop through - so both directions are pinned here.
"""

from src.agent.grounding_annotations import ClaimVerdict
from src.agent.source_pages import SourcePage
from src.agent.specifics_net import (
    REASON,
    SITE_REASON,
    missed_prices,
    missed_sites,
    missed_specifics,
)


def _page(url: str, text: str = "") -> SourcePage:
    return SourcePage(title="Page", url=url, text=text)


def _claim(quote: str) -> ClaimVerdict:
    return ClaimVerdict(quote=quote, verdict="not_found")


def _quotes(claims: list[ClaimVerdict]) -> list[str]:
    return [c.quote for c in claims]


# --- prices ---


def test_a_price_found_in_the_sources_is_not_flagged() -> None:
    assert missed_prices("Kolo stojí 4 990 Kč.", "Cena: 4 990 Kč", []) == []


def test_an_unsourced_price_is_flagged_as_not_found() -> None:
    missed = missed_prices("Kolo stojí 4 990 Kč. Helma je za 450 Kč.", "Cena: 4 990 Kč", [])
    assert _quotes(missed) == ["450 Kč"]
    assert missed[0].verdict == "not_found"
    assert missed[0].reason == REASON


def test_thousands_separators_and_decimal_zeros_are_normalised() -> None:
    answer = "Kolo stojí 1 299 Kč a zámek 6 490 Kč."
    assert missed_prices(answer, "kolo 1299,- / zámek 6490.0 CZK", []) == []


def test_every_currency_form_is_recognised() -> None:
    missed = missed_prices("Stojí €15, 20 EUR, 30 CZK nebo 40 Kč.", "", [])
    assert _quotes(missed) == ["€15", "20 EUR", "30 CZK", "40 Kč"]


def test_a_range_is_flagged_when_one_end_is_unsourced() -> None:
    missed = missed_prices("Ojeté stojí 1 200–1 500 Kč.", "od 1 200 Kč", [])
    assert _quotes(missed) == ["1 200–1 500 Kč"]


def test_a_range_with_both_ends_sourced_is_not_flagged() -> None:
    assert missed_prices("Ojeté stojí 1 200–1 500 Kč.", "1200 až 1500", []) == []


def test_a_price_the_verifier_already_listed_is_not_double_flagged() -> None:
    assert missed_prices("Helma je za 450 Kč.", "", [_claim("za 450 Kč")]) == []


def test_a_zero_price_is_not_flagged() -> None:
    assert missed_prices("Doprava za 0 Kč.", "", []) == []


def test_the_answers_own_conversion_is_not_a_new_price() -> None:
    answer = "Celkem 43 300 Kč (cca 1 730 €) za sestavu."
    assert missed_prices(answer, "43 300 Kč", []) == []


def test_a_price_in_a_sentence_marked_unverified_is_not_flagged() -> None:
    assert missed_prices("Cena kolem 999 Kč (neověřeno).", "", []) == []
    assert missed_prices("It costs 20 EUR, not verified.", "", []) == []


def test_empty_inputs_flag_no_prices() -> None:
    assert missed_prices("", "", []) == []
    assert missed_prices("Bez ceny, jen text.", "", []) == []


# --- sites ---


def test_a_linked_site_the_turn_read_is_not_flagged() -> None:
    answer = "Viz [Cyklobazar](https://www.cyklobazar.cz/kola)."
    assert missed_sites(answer, [_page("https://cyklobazar.cz/inzerat/1")], []) == []


def test_a_linked_site_the_turn_never_read_is_flagged_by_its_link_text() -> None:
    answer = "Viz [Bazar kol](https://www.cyklobazar.cz/kola)."
    missed = missed_sites(answer, [_page("https://www.alza.cz/")], [])
    assert _quotes(missed) == ["Bazar kol"]
    assert missed[0].reason == SITE_REASON


def test_a_bare_domain_the_turn_never_read_is_flagged() -> None:
    missed = missed_sites("Zkus taky sbazar.cz.", [_page("https://bazos.cz/")], [])
    assert _quotes(missed) == ["sbazar.cz"]


def test_hosts_match_across_www_subdomains_and_case() -> None:
    answer = "Viz [obchod](https://shop.alza.cz/a) nebo ALZA.cz."
    assert missed_sites(answer, [_page("https://www.alza.cz/kola")], []) == []


def test_co_uk_keeps_three_labels() -> None:
    read = [_page("https://news.bbc.co.uk/article")]
    assert missed_sites("Viz bbc.co.uk.", read, []) == []
    assert _quotes(missed_sites("Viz itv.co.uk.", read, [])) == ["itv.co.uk"]


def test_a_site_is_flagged_once_however_often_it_appears() -> None:
    answer = "Viz [první](https://a.cz) a [druhý](https://www.a.cz/2)."
    assert _quotes(missed_sites(answer, [], [])) == ["první"]


def test_a_site_the_verifier_already_covered_is_not_double_flagged() -> None:
    assert missed_sites("Zkus sbazar.cz dnes.", [], [_claim("Zkus sbazar.cz")]) == []


def test_a_site_named_in_the_turns_own_text_is_not_flagged() -> None:
    assert missed_sites("Zkus sbazar.cz.", [], [], mentioned="user asked about sbazar.cz") == []


def test_an_email_address_is_not_a_site() -> None:
    assert missed_sites("Napiš na info@shop.cz.", [], []) == []


def test_a_site_in_a_sentence_marked_unverified_is_not_flagged() -> None:
    assert missed_sites("Možná sbazar.cz, ale nepodařilo se ověřit.", [], []) == []


def test_empty_inputs_flag_no_sites() -> None:
    assert missed_sites("", [], []) == []


# --- combined ---


def test_missed_specifics_reports_prices_then_sites() -> None:
    missed = missed_specifics("Kolo za 500 Kč na bazos.cz.", "", [], [])
    assert _quotes(missed) == ["500 Kč", "bazos.cz"]


def test_known_text_backs_both_prices_and_sites() -> None:
    answer = "Kolo za 500 Kč na bazos.cz."
    assert missed_specifics(answer, "", [], [], known="Uživatel: 500 Kč, bazos.cz") == []


def test_missed_specifics_with_empty_inputs_is_empty() -> None:
    assert missed_specifics("", "", [], []) == []
