"""Runs a deep-research plan's subagents in parallel, with deadlines.

Each sub-question gets a subagent (subagent.run_subagent) with its own request
id and cancel token, so a deadline, Finish now or Stop can cut it individually;
what it read before that stays on the shared board. A per-worker semaphore
bounds subagents across concurrent runs (two family members at once).
"""

import contextvars
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any

from src.agent.cancellation import TurnCancelled, register_token, token_for, unregister_token
from src.agent.deep_research.board import BoardEntry, ResearchBoard
from src.agent.deep_research.briefs import build_brief
from src.agent.deep_research.plan import DeepResearchPlan
from src.agent.deep_research.subagent import ItemResult, Status, run_subagent
from src.agent.source_pages import SourcePage
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

_POLL_SECONDS = 0.05
_slots: threading.BoundedSemaphore | None = None
_slots_lock = threading.Lock()


def _get_slots() -> threading.BoundedSemaphore:
    global _slots
    with _slots_lock:
        if _slots is None:
            _slots = threading.BoundedSemaphore(Config.DEEP_RESEARCH_MAX_CONCURRENT_SUBAGENTS)
        return _slots


def reset_slots(size: int) -> None:
    """Replace the per-worker semaphore (tests)."""
    global _slots
    with _slots_lock:
        _slots = threading.BoundedSemaphore(size)


class Orchestrator:
    def __init__(
        self,
        plan: DeepResearchPlan,
        emit: Callable[[dict[str, Any]], None],
        run_id: str,
        today: str,
        recent_turns: str,
    ) -> None:
        self.plan = plan
        self.emit = emit
        self.run_id = run_id
        self.today = today
        self.recent_turns = recent_turns
        self.board = ResearchBoard(on_post=self._on_post)
        self._finish = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._running: dict[int, float] = {}
        self._cut: dict[int, Status] = {}

    def _on_post(self, entry: BoardEntry) -> None:
        self.emit({"type": "research_finding", "agent": entry.agent, "text": entry.text})

    def _rid(self, index: int) -> str:
        return f"{self.run_id}-{index}"

    def _halted(self) -> bool:
        return self._finish.is_set() or self._stop.is_set()

    def run(self) -> list[ItemResult]:
        """Results by index. Raises TurnCancelled after stop()."""
        items = self.plan.sub_questions
        self.emit(
            {
                "type": "research_plan",
                "items": list(items),
                "minutes": self.plan.estimate.get("minutes"),
                "started_at": round(time.time() * 1000),
            }
        )
        results: list[ItemResult | None] = [None] * len(items)
        with ThreadPoolExecutor(Config.DEEP_RESEARCH_PARALLELISM, "deep-research") as pool:
            futures = {
                pool.submit(contextvars.copy_context().run, self._item, i): i
                for i in range(len(items))
            }
            pending = set(futures)
            while pending:
                done, pending = wait(pending, timeout=_POLL_SECONDS)
                for future in done:
                    results[futures[future]] = future.result()
                self._enforce_deadlines()
        if self._stop.is_set():
            raise TurnCancelled
        final = [r for r in results if r is not None]
        self.emit({"type": "research_sources", "count": len(merge_pages(final, self.board))})
        return final

    def _item(self, index: int) -> ItemResult:
        slots = _get_slots()
        if not slots.acquire(blocking=False):
            self.emit({"type": "research_item", "index": index, "status": "waiting"})
            while not slots.acquire(timeout=_POLL_SECONDS):
                if self._halted():
                    return self._finish_item(ItemResult(index, "skipped", ""))
        try:
            if self._halted():
                return self._finish_item(ItemResult(index, "skipped", ""))
            return self._finish_item(self._research(index))
        finally:
            slots.release()

    def _research(self, index: int) -> ItemResult:
        rid = self._rid(index)
        register_token(rid)
        with self._lock:
            self._running[index] = time.monotonic()
        self.emit({"type": "research_item", "index": index, "status": "started"})
        brief = build_brief(self.plan, index, self.today, self.recent_turns)
        try:
            return run_subagent(brief, self.board, index, rid)
        except TurnCancelled:
            status = self._cut.get(index, "skipped")
            return ItemResult(index, status, "", self.board.pages_of(index))
        except Exception:
            logger.warning("Deep research subagent failed", exc_info=True, extra={"index": index})
            return ItemResult(index, "failed", "", self.board.pages_of(index))
        finally:
            with self._lock:
                self._running.pop(index, None)
            unregister_token(rid)

    def _finish_item(self, result: ItemResult) -> ItemResult:
        self.emit(
            {
                "type": "research_item",
                "index": result.index,
                "status": result.status,
                "pages": len(result.pages),
            }
        )
        return result

    def _cut_running(self, status: Status, only_overdue: bool = False) -> None:
        now = time.monotonic()
        timeout = Config.DEEP_RESEARCH_SUBAGENT_TIMEOUT_SECONDS
        with self._lock:
            targets = [
                i
                for i, started in self._running.items()
                if i not in self._cut and (not only_overdue or now - started > timeout)
            ]
            for i in targets:
                self._cut[i] = status
        for i in targets:
            token = token_for(self._rid(i))
            if token:
                token.cancel()

    def _enforce_deadlines(self) -> None:
        self._cut_running("timed_out", only_overdue=True)

    def finish_now(self) -> None:
        """Cut the remaining research; the report is written from what is there."""
        self._finish.set()
        self._cut_running("skipped")

    def stop(self) -> None:
        """End the run without a report."""
        self._stop.set()
        self._cut_running("skipped")


def merge_pages(results: list[ItemResult], board: ResearchBoard) -> list[SourcePage]:
    """All pages read, de-duplicated by URL in first-read order, capped and trimmed."""
    merged: dict[str, SourcePage] = {}
    for page in [p for r in results for p in r.pages] + board.pages():
        if page.url not in merged:
            merged[page.url] = page
    limit = Config.DEEP_RESEARCH_PAGE_MAX_CHARS
    capped = list(merged.values())[: Config.DEEP_RESEARCH_MAX_PAGES]
    return [SourcePage(p.title, p.url, p.text[:limit]) for p in capped]
