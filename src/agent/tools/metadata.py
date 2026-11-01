"""Extract-only tools: structured metadata reported alongside a response.

These tools replace the fragile <!-- METADATA: {...} --> text block approach.
The model calls them via Gemini's function calling (schema-validated), and the
server reads the args straight off the AIMessage - no JSON parsing needed.

Unlike real tools, these are never executed when the model also produced text:
there is nothing to do beyond recording the args, so `should_continue` ends the
turn instead of paying for another LLM round-trip. Anything that performs a
side effect the model needs the result of does NOT belong here - see
`src/agent/tools/memory.py`, which was moved out of this module for exactly
that reason.
"""

from langchain_core.tools import tool
from pydantic import BaseModel, Field


@tool
def set_conversation_title(title: str) -> str:
    """Update the conversation title when it no longer matches the conversation.

    Call this when the conversation's scope has clearly widened or narrowed
    away from the current title shown in your context. Do NOT call it for
    minor drift or on every message.

    Args:
        title: The new title. Must start with a single relevant emoji followed
            by a space, then 3-6 words in the user's language. No quotes.
    """
    return f"Conversation title updated to: {title}"


class FactEdit(BaseModel):
    """One conversation fact to set: a short key and the fact itself."""

    key: str = Field(description="Short slug naming the fact, e.g. partition-walls")
    text: str = Field(description="The fact, one short sentence (max 200 characters)")


@tool
def record_conversation_facts(
    set: list[FactEdit] | None = None,
    remove: list[str] | None = None,
) -> str:
    """Record facts the user has settled in THIS conversation.

    Use it for corrections, decisions, constraints, things already done, and
    identifiers or results worked out here - anything later answers in this
    conversation must not contradict. Not for facts about the user in
    general: those go to manage_memory. Replace a fact by setting its key
    again; remove facts that no longer hold.

    Args:
        set: Facts to add or replace, each with a short key and the fact.
        remove: Keys of facts that no longer hold.
    """
    return "Conversation facts recorded."


# Tools whose args are extracted post-hoc and whose execution can be skipped.
# (cite_sources was removed Sep 2026: source chips now come from the pages a
# turn read - see content.extract_read_sources)
EXTRACT_ONLY_TOOL_NAMES = frozenset({"set_conversation_title", "record_conversation_facts"})
