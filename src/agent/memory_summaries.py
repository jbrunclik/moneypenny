"""Short summaries of long memories for the per-turn context.

The memory list is re-sent every turn, uncached by design (6-14k characters
per user, Nov 2026); each long memory shows a Flash-Lite summary there and
the full text is a search_memory id lookup away
(docs/superpowers/specs/2026-11-15-cost-telemetry-design.md). The scheduler
pass writes summaries for memories that have none - new ones, and edited
ones whose summary a trigger cleared - so no write path needs a hook.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from src.agent.content import extract_text_content
from src.agent.gemini_clients import chat_model
from src.config import Config
from src.db.models import Memory, db
from src.services.side_costs import record_side_cost
from src.utils.logging import get_logger

logger = get_logger(__name__)

_PROMPT = """Condense this note an assistant keeps about its user into at most {limit}
characters. Keep names, numbers, dates and the point a reader would act on;
drop filler. Same language as the note. Output only the condensed text.

Note ({category}): {content}"""


def summarize_pending() -> int:
    """Summarise up to MEMORY_SUMMARIES_PER_PASS memories that need one; how
    many were written. A failed one stays without a summary (shown whole)."""
    limit = Config.MEMORY_SUMMARY_MAX_CHARS
    written = 0
    for memory in db.memories_needing_summary(limit, Config.MEMORY_SUMMARIES_PER_PASS):
        summary = _summarize(memory)
        if summary and db.set_memory_summary(memory.id, memory.content, summary):
            written += 1
    if written:
        logger.info("Memory summaries written", extra={"count": written})
    return written


def _summarize(memory: Memory) -> str | None:
    model = chat_model(
        Config.MEMORY_SUMMARY_MODEL,
        timeout=Config.MEMORY_SUMMARY_TIMEOUT_SECONDS,
        max_retries=0,
    )
    prompt = _PROMPT.format(
        limit=Config.MEMORY_SUMMARY_MAX_CHARS,
        category=memory.category or "fact",
        content=memory.content,
    )
    try:
        response = model.invoke([HumanMessage(content=prompt)])
    except Exception:  # retried on the next pass; the memory shows whole meanwhile
        logger.warning("Memory summary failed", extra={"memory_id": memory.id}, exc_info=True)
        return None
    record_side_cost("memory_summary", Config.MEMORY_SUMMARY_MODEL, response, memory.user_id)
    text = " ".join(extract_text_content(response.content).split())
    return text[: Config.MEMORY_SUMMARY_MAX_CHARS] or None
