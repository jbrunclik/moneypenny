"""One deep-research subagent: the delegate loop on one sub-question."""

from dataclasses import dataclass, field
from typing import Any, Literal

from src.agent.deep_research.board import ResearchBoard, share_finding_tool, wrap_research_tools
from src.agent.round_cap import round_cap_override
from src.agent.source_pages import SourcePage, turn_pages
from src.agent.tool_results import get_full_tool_results, set_current_request_id
from src.config import Config

Status = Literal["done", "failed", "skipped", "timed_out"]


@dataclass
class ItemResult:
    index: int
    status: Status
    digest: str
    pages: list[SourcePage] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


def run_subagent(brief: str, board: ResearchBoard, index: int, request_id: str) -> ItemResult:
    """Research one sub-question. Raises TurnCancelled when its token is cancelled."""
    # Imported here: tools -> ... -> agent would be circular at module load
    from src.agent.agent import ChatAgent
    from src.agent.prompt_texts.deep_research import DEEP_RESEARCH_SUBAGENT_PROMPT
    from src.agent.tools import fetch_url, research, web_search
    from src.agent.tools.delegate import _in_delegate

    tools: list[Any] = [
        *wrap_research_tools([research, web_search, fetch_url], board, index),
        share_finding_tool(board, index),
    ]
    set_current_request_id(request_id)
    nested = _in_delegate.set(True)  # no delegate_task / propose_deep_research inside
    try:
        with round_cap_override(Config.DEEP_RESEARCH_SUBAGENT_MAX_ROUNDS):
            agent = ChatAgent(
                model_name=Config.DEEP_RESEARCH_SUBAGENT_MODEL,
                with_tools=True,
                tools=tools,
                enable_context_cache=False,
                system_prompt_override=DEEP_RESEARCH_SUBAGENT_PROMPT,
            )
            text, _tools, usage, messages = agent.chat_batch(text=brief)
    finally:
        _in_delegate.reset(nested)
        get_full_tool_results(request_id)  # pops this subagent's tool results
        set_current_request_id(None)
    pages = {p.url: p for p in [*turn_pages(messages), *board.pages_of(index)]}
    return ItemResult(
        index,
        "done",
        text or "",
        list(pages.values()),
        {
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "cached_input_tokens": int(usage.get("cached_input_tokens", 0)),
        },
    )
