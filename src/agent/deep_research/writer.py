"""The deep-research report: Pro writes it from digests, the board and pages.

The report carries no citation markers - the grounding check numbers its claims
afterwards against the same numbered pages. A small Flash call then extracts
follow-up questions for the next round (no heading to parse, any language).
"""

from collections.abc import Iterator
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from src.agent.content import extract_text_content
from src.agent.deep_research.board import ResearchBoard, agent_label
from src.agent.deep_research.plan import DeepResearchPlan
from src.agent.deep_research.subagent import ItemResult
from src.agent.prompt_texts.deep_research import FOLLOWUP_PROMPT, REPORT_PROMPT
from src.agent.source_pages import SourcePage
from src.agent.tools.web import wrap_untrusted_content
from src.agent.turn_usage import TokenTotals
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

_UNTRUSTED_MARK = "[UNTRUSTED WEB CONTENT"


class FollowUps(BaseModel):
    """Follow-up research questions for the next round."""

    questions: list[str] = Field(default_factory=list, description="2-4 questions, or none")


def _page_block(number: int, page: SourcePage) -> str:
    text = (
        page.text
        if page.text.startswith(_UNTRUSTED_MARK)
        else wrap_untrusted_content(page.text, page.url)
    )
    return f"[{number}] {page.title} ({page.url})\n{text}"


def _read_label(status: str, result: ItemResult | None) -> str:
    """Status plus pages read: a digest from no page is unverified (snippets or memory)."""
    n = len(result.pages) if result else 0
    if n == 0:
        return f"{status}, no pages read - unverified"
    return f"{status}, {n} {'page' if n == 1 else 'pages'} read"


def _items_block(plan: DeepResearchPlan, results: list[ItemResult]) -> str:
    by_index = {r.index: r for r in results}
    lines = []
    for i, question in enumerate(plan.sub_questions):
        result = by_index.get(i)
        status = result.status if result else "skipped"
        digest = result.digest.strip() if result and result.digest.strip() else "(no digest)"
        lines.append(
            f"## Sub-question {i + 1} [{_read_label(status, result)}]: {question}\n{digest}"
        )
    return "\n\n".join(lines)


def report_messages(
    plan: DeepResearchPlan,
    results: list[ItemResult],
    board: ResearchBoard,
    pages: list[SourcePage],
    today: str,
) -> tuple[SystemMessage, HumanMessage]:
    """The writer's input: question, context, digests, board, numbered pages."""
    system = SystemMessage(
        content=REPORT_PROMPT.format(today=today, max_words=Config.DEEP_RESEARCH_REPORT_MAX_WORDS)
    )
    board_lines = [
        f"{agent_label(e.agent)} {'lead: ' if e.kind == 'lead' else ''}{e.text}"
        for e in board.entries()
    ]
    parts = [
        f"QUESTION: {plan.question}",
        f"ABOUT THE USER: {plan.context or '(nothing specific)'}",
    ]
    if plan.previous_report:
        parts.append(f"EARLIER ROUND'S REPORT (build on it):\n{plan.previous_report}")
    parts += [
        f"AGENT DIGESTS:\n{_items_block(plan, results)}",
        "SHARED BY THE AGENTS:\n"
        + wrap_untrusted_content("\n".join(board_lines) or "(nothing)", "the research agents"),
        "PAGES:\n" + "\n\n".join(_page_block(i, p) for i, p in enumerate(pages, 1)),
    ]
    return system, HumanMessage(content="\n\n".join(parts))


def writer_model() -> ChatGoogleGenerativeAI:
    from src.agent.graph import create_chat_model

    return create_chat_model(Config.DEEP_RESEARCH_WRITER_MODEL, with_tools=False)


def stream_report(messages: Any, model: Any, totals: TokenTotals) -> Iterator[str]:
    """Text chunks of the report; usage is added to totals."""
    for chunk in model.stream(messages):
        totals.add_from(chunk)
        text = extract_text_content(chunk.content)
        if text:
            yield text


def extract_followups(report: str) -> list[str]:
    """2-4 follow-up research questions from the report ([] on any failure)."""
    try:
        llm = ChatGoogleGenerativeAI(
            model=Config.DEEP_RESEARCH_SUBAGENT_MODEL,
            google_api_key=Config.GEMINI_API_KEY,
            temperature=0,
            max_retries=Config.AGENT_MODEL_SDK_MAX_RETRIES,
        )
        out = llm.with_structured_output(FollowUps).invoke(FOLLOWUP_PROMPT.format(report=report))
    except Exception:
        logger.warning("Deep research follow-up extraction failed", exc_info=True)
        return []
    questions = out.questions if isinstance(out, FollowUps) else []
    return [q.strip() for q in questions if q.strip()][: Config.DEEP_RESEARCH_MAX_SUB_QUESTIONS]
