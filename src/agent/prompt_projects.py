"""The `# Project:` section of a project chat's per-turn context."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.prompt_documents import document_line
from src.agent.prompt_memory import memory_line
from src.agent.prompt_texts.projects import (
    PROJECT_SECTION_GUIDANCE,
    PROJECT_SECTION_HEADER,
    PROJECT_SHARED_RULE,
)
from src.config import Config
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.agent.project_context import ProjectContext
    from src.db.models import Memory

logger = get_logger(__name__)


def _memory_line(ctx: ProjectContext, mem: Memory) -> str:
    author = ctx.author_names.get(mem.user_id) if ctx.shared else None
    return memory_line(mem, author=author)


def format_project_section(ctx: ProjectContext) -> str:
    """The project's instructions, memory and documents; empty blocks are left out."""
    others = ", ".join(n for n in ctx.other_member_names if n)
    shared = f" (shared with {others})" if ctx.shared and others else ""
    parts = [
        PROJECT_SECTION_HEADER.format(name=" ".join(ctx.name.split()), shared=shared),
        PROJECT_SECTION_GUIDANCE,
    ]
    if ctx.shared:
        parts.append(PROJECT_SHARED_RULE)
    if ctx.instructions.strip():
        parts.append("Instructions:\n" + ctx.instructions.strip())
    if ctx.memories:
        header = f"Project memory ({len(ctx.memories)}/{Config.PROJECT_MEMORY_MAX_ENTRIES}):"
        parts.append("\n".join([header, *(_memory_line(ctx, m) for m in ctx.memories)]))
    if ctx.documents:
        header = f"Project documents ({len(ctx.documents)}/{Config.PROJECT_DOCUMENTS_MAX_ENTRIES}):"
        parts.append("\n".join([header, *(document_line(d) for d in ctx.documents)]))
    section = "\n\n".join(parts)
    logger.info(
        "Project context",
        extra={"project_id": ctx.id, "shared": ctx.shared, "chars": len(section)},
    )
    return section
