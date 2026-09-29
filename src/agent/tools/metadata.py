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


# Tools whose args are extracted post-hoc and whose execution can be skipped.
# (cite_sources was removed Sep 2026: source chips now come from the pages a
# turn read - see content.extract_read_sources)
EXTRACT_ONLY_TOOL_NAMES = frozenset({"set_conversation_title"})
