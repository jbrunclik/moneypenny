"""Artifact refs ({id, version, title}) from a turn's artifact tool results.

The tools put the ref in their LLM-visible JSON (src/agent/tools/artifacts.py),
so it survives the ``_full_result`` stripping that streamed ToolMessages get.
The stream turns each into an ``artifact`` event; the save path stores the
turn's refs on the reply (``messages.artifacts``).
"""

import json
from typing import Any

from langchain_core.messages import ToolMessage

from src.agent.tools.artifacts import ARTIFACT_TOOL_NAMES
from src.db.models.dataclasses import ArtifactShown


def artifact_ref_from_tool_content(tool_name: str | None, content: Any) -> ArtifactShown | None:
    """The ref from a successful create/update result, else None."""
    if tool_name not in ARTIFACT_TOOL_NAMES or not isinstance(content, str):
        return None
    try:
        body = json.loads(content)
    except ValueError, TypeError:
        return None
    ref = body.get("artifact") if isinstance(body, dict) and body.get("success") else None
    if not isinstance(ref, dict) or not {"id", "version", "title"} <= set(ref):
        return None
    return {"id": str(ref["id"]), "version": int(ref["version"]), "title": str(ref["title"])}


def extract_artifact_refs(result_messages: list[Any]) -> list[ArtifactShown]:
    """The turn's refs in order; an artifact changed twice keeps its last version
    at the position it first appeared."""
    by_id: dict[str, ArtifactShown] = {}
    for msg in result_messages:
        if not isinstance(msg, ToolMessage):
            continue
        ref = artifact_ref_from_tool_content(msg.name, msg.content)
        if ref:
            by_id[ref["id"]] = ref
    return list(by_id.values())
