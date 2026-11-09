"""The [SYSTEM GUIDANCE] block notes ride in on a user's text (one format,
shared by the chat turn and the eval harness)."""

from src.agent.guidance import with_guidance


def test_notes_follow_the_text_in_one_block() -> None:
    assert with_guidance("Ano", ["The user approved: X", None, ""]) == (
        "Ano\n\n[SYSTEM GUIDANCE]\nThe user approved: X\n[/SYSTEM GUIDANCE]"
    )


def test_no_notes_leave_the_text_alone() -> None:
    assert with_guidance("Ano", [None, ""]) == "Ano"
