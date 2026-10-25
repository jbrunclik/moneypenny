"""Artifact tools: sandboxed HTML/JS the agent shows inline under its reply.

Spec: docs/superpowers/specs/2026-10-11-inline-artifacts-design.md. The tools
write versions straight to the database (so an id exists within the turn) and
return a small LLM-visible ``artifact`` ref {id, version, title}: the save path
reads it from the turn's ToolMessages and the stream turns it into an
``artifact`` event, so nothing rides in ``_full_result`` (which the streamed
ToolMessage no longer carries).
"""

import json

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.agent.prompt_texts.artifacts import CREATE_ARTIFACT_DESCRIPTION
from src.agent.tools.context import get_conversation_context
from src.agent.tools.errors import tool_error
from src.config import Config
from src.db.models import db
from src.db.models.dataclasses import Artifact
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Tools whose successful results put an artifact version under the reply
ARTIFACT_TOOL_NAMES = frozenset({"create_artifact", "update_artifact"})
_EXCERPT_CHARS = 300
_PROBE_CHARS = 20


class ArtifactEdit(BaseModel):
    """One find/replace edit of an artifact's HTML."""

    find: str = Field(description="Exact text to replace; must occur exactly once")
    replace: str = Field(description="Replacement text")


class EditError(ValueError):
    """An update_artifact edit that does not match exactly once."""


def _excerpt(html: str, needle: str) -> str:
    """The document around the needle's first chars, or its start."""
    probe = needle[:_PROBE_CHARS]
    at = html.find(probe) if probe else -1
    start = max(0, at - _EXCERPT_CHARS // 2) if at >= 0 else 0
    return html[start : start + _EXCERPT_CHARS]


def apply_edits(html: str, edits: list[dict[str, str]]) -> str:
    """Apply find/replace edits in order; each find must match exactly once."""
    for i, edit in enumerate(edits):
        find, replace = edit.get("find", ""), edit.get("replace", "")
        count = html.count(find) if find else 0
        if count != 1:
            where = "not found" if count == 0 else f"found {count} times"
            raise EditError(
                f"edit {i + 1}: find text {where}. Nearby: {_excerpt(html, find)!r}. "
                "Copy the find text exactly (read_artifact shows the current HTML)."
            )
        html = html.replace(find, replace, 1)
    return html


def _fail(error: str) -> str:
    return tool_error(error, success=False)


def _ok(art_id: str, version: int, title: str, message: str) -> str:
    ref = {"id": art_id, "version": version, "title": title}
    return json.dumps({"success": True, "artifact": ref, "message": message})


def _too_big(html: str) -> str | None:
    size = len(html.encode("utf-8"))
    if size > Config.ARTIFACT_MAX_BYTES:
        return f"html is {size} bytes; the limit is {Config.ARTIFACT_MAX_BYTES}. Simplify it."
    return None


def _revised(latest: str, edits: list[dict[str, str]], html: str | None) -> str:
    """The new version's html (raises EditError on a bad edit or an oversized result)."""
    result = html if html is not None else apply_edits(latest, edits)
    if error := _too_big(result):
        raise EditError(error)
    return result


def _own_artifact(artifact_id: str) -> Artifact | None:
    """The artifact when it belongs to the current conversation."""
    conv_id, _ = get_conversation_context()
    art = db.get_artifact(artifact_id)
    return art if art and conv_id and art.conversation_id == conv_id else None


@tool(description=CREATE_ARTIFACT_DESCRIPTION)
def create_artifact(title: str, html: str) -> str:
    conv_id, user_id = get_conversation_context()
    if not conv_id or not user_id:
        return _fail("Artifacts need a conversation.")
    if not title.strip() or not html.strip():
        return _fail("title and html must not be empty.")
    if error := _too_big(html):
        return _fail(error)
    count = db.count_conversation_artifacts(conv_id)
    if count >= Config.ARTIFACT_MAX_PER_CONVERSATION:
        return _fail(
            f"This conversation has {count} artifacts, the limit. Update an existing one instead."
        )
    art, version = db.create_artifact(conv_id, user_id, title.strip(), html)
    logger.info(
        "Artifact created",
        extra={"artifact_id": art.id, "conversation_id": conv_id, "size": len(html)},
    )
    return _ok(
        art.id,
        version.version,
        art.title,
        "Shown to the user below your reply. Don't repeat its contents in text; "
        "say in one sentence what it is.",
    )


@tool
def update_artifact(
    artifact_id: str,
    edits: list[ArtifactEdit] | None = None,
    html: str | None = None,
    title: str | None = None,
) -> str:
    """Change an artifact you made: saves a new version shown below your reply.

    Prefer small `edits` (exact find/replace pairs, each find occurring exactly
    once) over rewriting; pass `html` only to replace the whole page. If the
    artifact was made in an earlier turn, call read_artifact first so your find
    texts match the current HTML.

    Args:
        artifact_id: The artifact's id (from create_artifact or the conversation history).
        edits: Find/replace edits applied in order.
        html: The complete new page, instead of edits.
        title: A new title, when the artifact's purpose changed.
    """
    art = _own_artifact(artifact_id)
    if art is None:
        return _fail("Unknown artifact id.")
    if (edits is None) == (html is None):
        return _fail("Pass edits or html (exactly one).")
    plain = [ArtifactEdit.model_validate(e).model_dump() for e in edits or []]
    new_title = title.strip() if title and title.strip() else None
    try:
        # Edits apply to the latest html inside the write lock: parallel
        # updates of one artifact each build on the other's result
        version = db.revise_artifact(
            art.id, lambda latest: _revised(latest, plain, html), new_title
        )
    except EditError as e:
        return _fail(str(e))
    logger.info(
        "Artifact updated",
        extra={
            "artifact_id": art.id,
            "version": version.version,
            "mode": "html" if edits is None else "edits",
            "edit_count": len(edits or []),
        },
    )
    return _ok(
        art.id,
        version.version,
        new_title or art.title,
        f"Version {version.version} shown below your reply.",
    )


@tool
def read_artifact(artifact_id: str) -> str:
    """Read an artifact's current HTML (before editing one from an earlier turn).

    Args:
        artifact_id: The artifact's id from the conversation history.
    """
    art = _own_artifact(artifact_id)
    if art is None:
        return _fail("Unknown artifact id.")
    current = db.get_artifact_version(art.id, art.latest_version)
    ref = {"id": art.id, "version": art.latest_version, "title": art.title}
    return json.dumps({"success": True, "artifact": ref, "html": current.html if current else ""})
