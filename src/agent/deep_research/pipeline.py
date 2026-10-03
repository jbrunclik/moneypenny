"""One deep-research turn: progress events in, a normal `final` event out.

Runs in place of ChatAgent.stream_chat_events (the stream producer picks it
for a turn with a DeepResearchPlan), so resume, Stop and push work unchanged.
The orchestrator runs on a background thread; its events (emitted from many
subagent threads) are relayed in order through a queue.
"""

import contextvars
import queue
import threading
import time
from collections.abc import Callable, Generator, Iterator
from datetime import datetime
from typing import Any

from src.agent.cancellation import TurnCancelled, token_for
from src.agent.deep_research.offer import build_offer
from src.agent.deep_research.orchestrator import Orchestrator, merge_pages
from src.agent.deep_research.plan import DeepResearchPlan
from src.agent.deep_research.subagent import ItemResult
from src.agent.deep_research.writer import (
    extract_followups,
    report_messages,
    stream_report,
    writer_model,
)
from src.agent.grounding_check import GroundingOutcome, check_grounding_pages
from src.agent.retry import is_model_unavailable
from src.agent.source_pages import SourcePage
from src.agent.turn_usage import TokenTotals
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

_DONE = object()
_POLL_SECONDS = 0.2
# A quiet research phase (slow subagents, a slot wait) sends a research_tick
# this often, so a resumed reader's stall detector sees a live run
TICK_SECONDS = 60.0
STOPPED_TEXT = "Research stopped."
FAILED_TEXT = "Research failed: none of the sub-questions could be researched."


def run_deep_research(
    plan: DeepResearchPlan,
    recent_turns: str,
    request_id: str,
    finish_requested: Callable[[], bool] = lambda: False,
) -> Generator[dict[str, Any]]:
    """Events of one run, ending with the `final` event."""
    started = time.monotonic()
    today = datetime.now().astimezone().strftime("%A %Y-%m-%d")
    events: queue.Queue[Any] = queue.Queue()
    orchestrator = Orchestrator(plan, events.put, request_id, today, recent_turns)
    parent = token_for(request_id)
    if parent:
        parent.add_callback(orchestrator.stop)  # the user pressed Stop
    box: dict[str, Any] = {}
    threading.Thread(
        target=contextvars.copy_context().run,
        args=(_research, orchestrator, box, events),
        daemon=True,
        name="deep-research-orchestrator",
    ).start()
    finished_early = yield from _relay(events, orchestrator, finish_requested)
    if box.get("stopped"):
        # What the subagents spent up to the Stop is still billed
        yield _final(STOPPED_TEXT, _usage(TokenTotals(), orchestrator, None, [], None), "user")
        return
    results: list[ItemResult] = box.get("results") or []
    run = _run_data(plan, results, orchestrator, started, finished_early)
    if _found_nothing(results, orchestrator):
        yield _final(FAILED_TEXT, _usage(TokenTotals(), orchestrator, run, [], None))
        return
    yield from _report(plan, results, orchestrator, run, today, parent)


def _found_nothing(results: list[ItemResult], orchestrator: Orchestrator) -> bool:
    """Every item failed, or none read a page or wrote a digest: no report from nothing."""
    if all(r.status == "failed" for r in results):  # also true for no results
        return True
    return not merge_pages(results, orchestrator.board) and not any(
        r.digest.strip() for r in results
    )


def _research(orchestrator: Orchestrator, box: dict[str, Any], events: queue.Queue[Any]) -> None:
    try:
        box["results"] = orchestrator.run()
    except TurnCancelled:
        box["stopped"] = True
    except Exception:
        logger.error("Deep research orchestrator failed", exc_info=True)
        box["results"] = []
    finally:
        events.put(_DONE)


def _relay(
    events: queue.Queue[Any], orchestrator: Orchestrator, finish_requested: Callable[[], bool]
) -> Generator[dict[str, Any], None, bool]:
    """Yield orchestrator events until it is done; returns whether Finish now was used."""
    finished_early = False
    last_sent = time.monotonic()
    while True:
        try:
            event = events.get(timeout=_POLL_SECONDS)
        except queue.Empty:
            event = None
        if not finished_early and finish_requested():
            finished_early = True
            orchestrator.finish_now()
        if event is _DONE:
            return finished_early
        if event is None and time.monotonic() - last_sent >= TICK_SECONDS:
            event = {"type": "research_tick"}
        if event is not None:
            last_sent = time.monotonic()
            yield event


def _report(
    plan: DeepResearchPlan,
    results: list[ItemResult],
    orchestrator: Orchestrator,
    run: dict[str, Any],
    today: str,
    parent: Any,
) -> Iterator[dict[str, Any]]:
    pages = merge_pages(results, orchestrator.board)
    yield {"type": "research_writing"}
    totals = TokenTotals()
    messages = list(report_messages(plan, results, orchestrator.board, pages, today))
    chunks: list[str] = []
    model_used = yield from _write(messages, totals, chunks, parent)
    report = "".join(chunks)
    if parent and parent.cancelled:
        yield _final(
            report or STOPPED_TEXT,
            _usage(totals, orchestrator, run, pages, None),
            stop_reason="user",
        )
        return
    yield {"type": "grounding_started"}
    outcome = check_grounding_pages(
        report,
        pages,
        "",
        known=f"Today is {today}.",
        max_source_chars=Config.DEEP_RESEARCH_GROUNDING_MAX_SOURCE_CHARS,
        max_claims=Config.DEEP_RESEARCH_GROUNDING_MAX_CLAIMS,
    )
    followups = extract_followups(report)
    if followups:
        run["followup"] = build_offer(
            {"question": plan.question, "context": plan.context, "sub_questions": followups},
            kind="followup",
            round_=plan.round + 1,
        )
    usage = _usage(totals, orchestrator, run, pages, outcome)
    usage["answer_model"] = model_used
    yield _final(report, usage)


def _write(
    messages: list[Any], totals: TokenTotals, chunks: list[str], parent: Any
) -> Generator[dict[str, Any], None, str]:
    """Stream the report as token events; returns the model that wrote it.

    A writer model that is down before the first token falls back to the
    other tier (as chat turns do, src/agent/graph.py).
    """
    from src.agent.graph import create_chat_model, other_model_tier

    model_name = Config.DEEP_RESEARCH_WRITER_MODEL
    try:
        for text in stream_report(messages, writer_model(), totals):
            chunks.append(text)
            yield {"type": "token", "text": text}
            if parent and parent.cancelled:
                break
        return model_name
    except Exception as error:
        fallback = other_model_tier(model_name)
        if chunks or fallback is None or not is_model_unavailable(error):
            raise
    logger.warning("Deep research writer unavailable, falling back", extra={"fallback": fallback})
    for text in stream_report(messages, create_chat_model(fallback, with_tools=False), totals):
        chunks.append(text)
        yield {"type": "token", "text": text}
    return fallback


def _run_data(
    plan: DeepResearchPlan,
    results: list[ItemResult],
    orchestrator: Orchestrator,
    started: float,
    finished_early: bool,
) -> dict[str, Any]:
    """The report message's research.run (spec "Run data")."""
    return {
        "round": plan.round,
        "question": plan.question,
        "context": plan.context,
        "offered_sub_questions": plan.offered_sub_questions,
        "sub_questions": plan.sub_questions,
        "items": [{"status": r.status, "pages": len(r.pages)} for r in results],
        "pages_read": len(orchestrator.board.pages()),
        "board": [
            {"agent": e.agent, "kind": e.kind, "text": e.text, "urls": e.urls}
            for e in orchestrator.board.entries()
        ],
        "cache_hits": orchestrator.board.cache_hits,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "estimate": plan.estimate,
        "finished_early": finished_early,
    }


def _usage(
    totals: TokenTotals,
    orchestrator: Orchestrator,
    run: dict[str, Any] | None,
    pages: list[SourcePage],
    outcome: GroundingOutcome | None,
) -> dict[str, Any]:
    usage: dict[str, Any] = {
        "input_tokens": totals.input_tokens,
        "output_tokens": totals.output_tokens,
        "cached_input_tokens": totals.cached_tokens,
        "tool_rounds": 0,
        "tool_call_count": 0,
        # Every started subagent, done or cut (orchestrator.spent)
        "deep_research_usage": [
            {"model": Config.DEEP_RESEARCH_SUBAGENT_MODEL, **u}
            for u in orchestrator.spent()
            if u.get("input_tokens") or u.get("output_tokens")
        ],
        "research_run": run,
        "research_sources": [{"title": p.title, "url": p.url} for p in pages],
    }
    if outcome and outcome.usage:
        usage["grounding_usage"] = outcome.usage
    if outcome and outcome.annotations:
        usage["grounding"] = {"annotations": outcome.annotations, "summary": outcome.summary}
    return usage


def _final(content: str, usage: dict[str, Any], stop_reason: str | None = None) -> dict[str, Any]:
    final: dict[str, Any] = {
        "type": "final",
        "content": content,
        "result_messages": [],
        "tool_results": [],
        "usage_info": usage,
    }
    if stop_reason:
        final["stop_reason"] = stop_reason
    return final
