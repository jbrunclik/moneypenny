"""Metadata tools for structured extraction of sources and memory operations.

These tools replace the fragile <!-- METADATA: {...} --> text block approach.
The model calls these tools via Gemini's function calling (schema-validated),
and the server extracts args from the AIMessage tool_calls - no parsing needed.
"""

from typing import Any

from langchain_core.tools import tool


@tool
def cite_sources(sources: list[dict[str, Any]]) -> str:
    """Report which web sources you referenced in your response.

    Call this tool after using web_search or fetch_url to cite the sources
    you actually used in your response. Only include sources you referenced.

    Args:
        sources: List of sources. Each dict must have "title" (str) and "url" (str).
    """
    return f"Noted {len(sources)} source(s)."


@tool
def manage_memory(operations: list[dict[str, Any]]) -> str:
    """Store, update, or delete user memories for personalization.

    Call this tool when you learn new facts about the user that should be
    remembered for future conversations.

    Args:
        operations: List of memory operations. Each dict must have:
            - "action": one of "add", "update", or "delete"
            - "content": text content (required for add/update)
            - "category": one of "preference", "fact", "context", "goal" (for add)
            - "id": memory ID like "mem-xxx" (required for update/delete)
    """
    return f"Processed {len(operations)} memory operation(s)."


# Set of metadata tool names for routing detection
METADATA_TOOL_NAMES = frozenset({"cite_sources", "manage_memory"})
