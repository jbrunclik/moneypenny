"""In-place markers for unverified specifics (src/agent/grounding_markers.py)."""

from src.agent.grounding_markers import mark_unverified

CS = "_(neověřeno)_"
EN = "_(unverified)_"


def test_nothing_flagged_leaves_answer_unchanged() -> None:
    assert mark_unverified("Answer.", [], [], "cs") == "Answer."


def test_marks_every_occurrence_in_czech() -> None:
    text = "Kupte u VeloRama. VeloRama má i servis."

    assert mark_unverified(text, ["VeloRama"], [], "cs") == (
        f"Kupte u VeloRama {CS}. VeloRama {CS} má i servis."
    )


def test_english_marker_for_other_and_unknown_languages() -> None:
    for language in ("en", "de", None):
        assert mark_unverified("Try VeloRama.", ["VeloRama"], [], language) == f"Try VeloRama {EN}."


def test_case_insensitive_match_keeps_original_spelling() -> None:
    assert mark_unverified("Try VeloRama.", ["velorama"], [], "en") == f"Try VeloRama {EN}."


def test_marker_goes_after_closing_emphasis() -> None:
    text = "Shops: **VeloRama** and *Bazoš*."

    assert mark_unverified(text, ["VeloRama", "Bazoš"], [], "en") == (
        f"Shops: **VeloRama** {EN} and *Bazoš* {EN}."
    )


def test_link_target_untouched_link_text_marked() -> None:
    text = "See [VeloRama](https://velorama.cz/brompton)."

    assert mark_unverified(text, ["VeloRama", "velorama.cz"], [], "en") == (
        f"See [VeloRama {EN}](https://velorama.cz/brompton)."
    )


def test_code_is_never_edited() -> None:
    text = "Run `VeloRama` or:\n```\nVeloRama\n```\nVeloRama"

    assert mark_unverified(text, ["VeloRama"], [], "en") == (
        f"Run `VeloRama` or:\n```\nVeloRama\n```\nVeloRama {EN}"
    )


def test_table_cells_keep_their_pipes() -> None:
    text = "| Shop | Price |\n|---|---|\n| VeloRama | 29 990 Kč |"

    assert mark_unverified(text, ["VeloRama", "29 990 Kč"], [], "cs") == (
        f"| Shop | Price |\n|---|---|\n| VeloRama {CS} | 29 990 Kč {CS} |"
    )


def test_overlapping_items_mark_once_longest_first() -> None:
    text = "VeloRama.cz and VeloRama"

    assert mark_unverified(text, ["VeloRama", "VeloRama.cz"], [], "en") == (
        f"VeloRama.cz {EN} and VeloRama {EN}"
    )


def test_never_marks_inside_a_word_or_domain() -> None:
    text = "Bazoš.cz, Bazošek, Velorama"

    assert mark_unverified(text, ["Bazoš", "Velo"], [], "cs") == text


def test_regex_metacharacters_are_literal() -> None:
    text = "C++ (2026) costs ~42,000 – 52,000 Kč."

    assert mark_unverified(text, ["~42,000 – 52,000 Kč", "(2026)"], [], "en") == (
        f"C++ (2026) {EN} costs ~42,000 – 52,000 Kč {EN}."
    )


def test_false_claim_marked_at_sentence_end_with_its_items() -> None:
    claim = "Verified: VeloRama prices were checked on its site."
    text = f"Buy at VeloRama.\n\n{claim}"

    assert mark_unverified(text, ["VeloRama"], [claim], "en") == (
        f"Buy at VeloRama {EN}.\n\nVerified: VeloRama {EN} prices were checked on its site. {EN}"
    )
