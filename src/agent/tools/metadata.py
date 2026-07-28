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


# Tools whose args are extracted post-hoc and whose execution can be skipped.
EXTRACT_ONLY_TOOL_NAMES = frozenset({"cite_sources"})
