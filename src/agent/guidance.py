"""The [SYSTEM GUIDANCE] block that carries notes on a user's text to the
agent (a lost turn's actions, proposal outcomes) - one format, shared by the
chat turn (chat_turn.TurnContext) and the eval harness."""

from collections.abc import Iterable

GUIDANCE_OPEN = "[SYSTEM GUIDANCE]"
GUIDANCE_CLOSE = "[/SYSTEM GUIDANCE]"


def with_guidance(text: str, notes: Iterable[str | None]) -> str:
    """The text with its notes in one guidance block (unchanged without notes)."""
    joined = "\n".join(note for note in notes if note)
    return f"{text}\n\n{GUIDANCE_OPEN}\n{joined}\n{GUIDANCE_CLOSE}" if joined else text
