"""A scripted deep-research run in place of the real pipeline."""

import time
from typing import Any

from tests.e2e_server.context import MOCK_CONFIG

DEEP_RESEARCH_REPORT = "Report: the transfer costs 1590 CZK and takes two days."


def _fake_item(index: int, step_s: float, finish_requested: Any) -> Any:
    """Scripted events of one sub-question: started, a finding, done."""
    yield {"type": "research_item", "index": index, "status": "started"}
    time.sleep(step_s)  # the configured step time
    if finish_requested():
        yield {"type": "research_item", "index": index, "status": "skipped", "pages": 0}
        return
    yield {"type": "research_finding", "agent": index, "text": f"Finding {index + 1}"}
    time.sleep(step_s)  # the configured step time
    yield {"type": "research_item", "index": index, "status": "done", "pages": 3 + index}


def mock_run_deep_research(
    plan: Any, recent_turns: str, request_id: str, finish_requested: Any = lambda: False
) -> Any:
    """A scripted deep-research run: progress events, a report, a follow-up offer."""
    from src.agent.deep_research.offer import build_offer

    step_s = MOCK_CONFIG["deep_research_step_ms"] / 1000
    started = time.time()
    yield {
        "type": "research_plan",
        "items": list(plan.sub_questions),
        "minutes": plan.estimate.get("minutes"),
        "started_at": round(started * 1000),
    }
    for index in range(len(plan.sub_questions)):
        yield from _fake_item(index, step_s, finish_requested)
    yield {"type": "research_sources", "count": 2}
    yield {"type": "research_writing"}
    for word in DEEP_RESEARCH_REPORT.split(" "):
        time.sleep(step_s / 5)  # the configured step time, per word
        yield {"type": "token", "text": f"{word} "}
    yield {"type": "grounding_started"}
    n = len(plan.sub_questions)
    run = {
        "round": plan.round,
        "question": plan.question,
        "context": plan.context,
        "offered_sub_questions": plan.offered_sub_questions,
        "sub_questions": plan.sub_questions,
        "items": [{"status": "done", "pages": 3 + i} for i in range(n)],
        "pages_read": sum(3 + i for i in range(n)),
        "board": [
            {"agent": i, "kind": "finding", "text": f"Finding {i + 1}", "urls": []}
            for i in range(n)
        ],
        "cache_hits": 1,
        "duration_ms": round((time.time() - started) * 1000),
        "estimate": plan.estimate,
        "finished_early": bool(finish_requested()),
        "followup": build_offer(
            {"question": plan.question, "context": plan.context, "sub_questions": ["Next step?"]},
            kind="followup",
            round_=plan.round + 1,
        ),
    }
    usage = {
        "input_tokens": 100,
        "output_tokens": 50,
        "research_run": run,
        "research_sources": [
            {"title": "Transfer prices", "url": "https://prices.example.cz"},
            {"title": "Office hours", "url": "https://office.example.cz"},
        ],
        "grounding": {
            "annotations": [
                {
                    "type": "claim",
                    "verdict": "supported",
                    "quote": "1590 CZK",
                    "source": 1,
                    "source_quote": "1590 CZK",
                },
            ],
            "summary": {"checked": True, "source_count": 2},
        },
        "answer_model": "gemini-3.1-pro-preview",
    }
    yield {
        "type": "final",
        "content": DEEP_RESEARCH_REPORT,
        "result_messages": [],
        "tool_results": [],
        "usage_info": usage,
    }
