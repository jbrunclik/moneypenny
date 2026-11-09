"""ask_choice: a clarifying question with 2-4 options, shown as a card.

One approval mechanism, step 5 (docs/features/proposals.md). The card is a
`question` proposal: its options only answer - tapping one sends its label as
the user's reply, typing its label or number does the same, and the turn that
message starts hears which was picked. A reply in the user's own words closes
the card. Never generic suggested replies: only a real fork the model cannot
settle from the conversation.
"""

from __future__ import annotations

from langchain_core.tools import tool

from src.agent.proposals import file_proposal, is_answer_word, normalize_answer, register_kind
from src.agent.tools.errors import tool_error
from src.db.models import Proposal, ProposalOption
from src.utils.logging import get_logger

logger = get_logger(__name__)

KIND = "question"
MIN_OPTIONS, MAX_OPTIONS = 2, 4
MAX_LABEL_CHARS = 60


def _refusal(options: list[str]) -> str | None:
    """Why these options cannot be told apart on a card, or None."""
    labels = [o.strip() for o in options]
    if not MIN_OPTIONS <= len(labels) <= MAX_OPTIONS:
        return f"Give 2-4 options, not {len(labels)}."
    read_as = {normalize_answer(label) for label in labels}
    if len(read_as) < len(labels) or not all(read_as):
        return "Make every option different (and not empty)."
    if any(len(label) > MAX_LABEL_CHARS for label in labels):
        return f"Keep each option short (at most {MAX_LABEL_CHARS} characters)."
    if any(is_answer_word(label) for label in labels):
        return "An option must not be a plain yes or no - name the choice itself."
    if any(normalize_answer(label).isdigit() for label in labels):
        return "An option must not be a number alone (a typed number picks by position)."
    return None


@tool
def ask_choice(question: str, options: list[str]) -> str:
    """Ask the user to choose when the request is ambiguous between a few
    concrete possibilities you cannot settle from the conversation (which of
    two dentist events, which approach to take). The user sees the question
    with one button per option; their pick arrives as their next message.
    Not for suggesting follow-ups or for yes/no questions.

    Args:
        question: The question, in the user's language, e.g. "Which dentist appointment?".
        options: 2-4 short, distinct choices, e.g. ["Thursday 9:00", "Friday 14:30"].
    """
    refusal = _refusal(options)
    if refusal is not None:
        return tool_error(f"Question NOT shown: {refusal}")
    choices: list[ProposalOption] = [
        {"label": label.strip(), "description": "", "payload": {}} for label in options
    ]
    try:
        file_proposal(KIND, question.strip(), {}, choices)
    except ValueError as e:  # no conversation to show it in
        return tool_error(str(e), retriable=False)
    logger.info("Question asked", extra={"options": len(choices)})
    labels = " / ".join(o["label"] for o in choices)
    return (
        f"QUESTION shown to the user as a card ({labels}). Stop here: end your reply "
        "with the question in one short sentence - don't list the options again. "
        "Their pick arrives as their next message."
    )


def apply_pick(proposal: Proposal, option: ProposalOption) -> str:
    """A pick only answers: it is the user's reply (nothing to apply)."""
    return option["label"]


register_kind(
    KIND,
    apply_pick,
    exclusive=True,
    outcomes={
        "approved": "The user picked for “{summary}”: {result}",
        "expired": "The question was closed without a pick: {summary}",
        "declined": "The user skipped the question: {summary}",
    },
)
