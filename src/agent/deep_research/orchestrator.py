"""Runs a deep-research plan's subagents in parallel, with deadlines.

Each sub-question gets a subagent (subagent.run_subagent) with its own request
id and cancel token, so a deadline, Finish now or Stop can cut it individually;
what it read before that stays on the shared board. Cancellation is checked
between tool rounds, so a subagent stuck inside one tool call (a hanging fetch,
search retries) is abandoned after DEEP_RESEARCH_CUT_GRACE_SECONDS: the run
keeps its board pages and moves on, the thread finishes on its own. A per-run
semaphore caps parallelism; a per-worker one bounds subagents across
concurrent runs (two family members at once).
"""

import contextvars
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import replace
from typing import Any

from src.agent.cancellation import TurnCancelled, register_token, token_for, unregister_token
from src.agent.deep_research.board import BoardEntry, ResearchBoard
from src.agent.deep_research.briefs import build_brief
from src.agent.deep_research.plan import DeepResearchPlan
from src.agent.deep_research.subagent import ItemResult, Status, run_subagent
from src.agent.source_pages import SourcePage
from src.agent.turn_usage import TokenTotals, collecting_model_usage
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
        self._cut_at: dict[int, float] = {}
        self._run_slots = threading.BoundedSemaphore(Config.DEEP_RESEARCH_PARALLELISM)
        self._held: dict[int, list[threading.BoundedSemaphore]] = {}
        self._finished: set[int] = set()
        self._totals: dict[int, TokenTotals] = {}

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
        # One thread per item: a thread stuck in a tool must not starve the queue
        pool = ThreadPoolExecutor(max(len(items), 1), "deep-research")
        try:
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
                pending = self._abandon_stuck(pending, futures, results)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if self._stop.is_set():
            raise TurnCancelled
        final = [r for r in results if r is not None]
        self.emit({"type": "research_sources", "count": len(merge_pages(final, self.board))})
        return final

    def _acquire(self, index: int, slots: threading.BoundedSemaphore, announce: bool) -> bool:
        """Take a slot (False when the run halts first); recorded for _release."""
        if not slots.acquire(blocking=False):
            if announce:
                self.emit({"type": "research_item", "index": index, "status": "waiting"})
            while not slots.acquire(timeout=_POLL_SECONDS):
                if self._halted():
                    return False
        with self._lock:
            self._held.setdefault(index, []).append(slots)
        return True

    def _release(self, index: int) -> None:
        """Give back an item's slots once (by the item, or when it is abandoned)."""
        with self._lock:
            held = self._held.pop(index, [])
        for slots in held:
            slots.release()

    def _item(self, index: int) -> ItemResult:
        try:
            if (
                not (
                    self._acquire(index, self._run_slots, announce=False)
                    and self._acquire(index, _get_slots(), announce=True)
                )
                or self._halted()
            ):
                return self._finish_item(ItemResult(index, "skipped", ""))
            return self._finish_item(self._research(index))
        finally:
            self._release(index)

    def _research(self, index: int) -> ItemResult:
        rid = self._rid(index)
        register_token(rid)
        with self._lock:
            self._running[index] = time.monotonic()
        self.emit({"type": "research_item", "index": index, "status": "started"})
        brief = build_brief(self.plan, index, self.today, self.recent_turns)
        totals = TokenTotals()
        with self._lock:
            self._totals[index] = totals
        try:
            # Every model call is priced as it happens: a cut turn returns no usage
            with collecting_model_usage(totals):
                result = run_subagent(brief, self.board, index, rid)
            return replace(result, usage=usage_of(totals))
        except TurnCancelled:
            status = self._cut.get(index, "skipped")
            return ItemResult(index, status, "", self.board.pages_of(index), usage_of(totals))
        except Exception:
            logger.warning("Deep research subagent failed", exc_info=True, extra={"index": index})
            return ItemResult(index, "failed", "", self.board.pages_of(index), usage_of(totals))
        finally:
            with self._lock:
                self._running.pop(index, None)
            unregister_token(rid)

    def _finish_item(self, result: ItemResult) -> ItemResult:
        with self._lock:
            if result.index in self._finished:
                return result  # abandoned earlier: the run has moved on
            self._finished.add(result.index)
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
                self._cut_at[i] = now
        for i in targets:
            token = token_for(self._rid(i))
            if token:
                token.cancel()

    def _abandon_stuck(
        self, pending: set[Any], futures: dict[Any, int], results: list[ItemResult | None]
    ) -> set[Any]:
        """Stop waiting for items cut longer than the grace ago; returns what is left."""
        now = time.monotonic()
        grace = Config.DEEP_RESEARCH_CUT_GRACE_SECONDS
        left = set()
        for future in pending:
            index = futures[future]
            with self._lock:
                stuck = index in self._running and now - self._cut_at.get(index, now) > grace
            if not stuck:
                left.add(future)
                continue
            logger.warning("Deep research subagent stuck after its cut", extra={"index": index})
            self._release(index)
            status = self._cut[index]
            with self._lock:
                spent = usage_of(self._totals.get(index, TokenTotals()))
            results[index] = self._finish_item(
                ItemResult(index, status, "", self.board.pages_of(index), spent)
            )
        return left

    def spent(self) -> list[dict[str, int]]:
        """What every started subagent has spent so far (done, cut or stuck)."""
        with self._lock:
            return [usage_of(t) for _i, t in sorted(self._totals.items())]

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


def usage_of(totals: TokenTotals) -> dict[str, int]:
    """A subagent's spend in the shape ItemResult.usage and cost pricing use."""
    return {
        "input_tokens": totals.input_tokens,
        "output_tokens": totals.output_tokens,
        "cached_input_tokens": totals.cached_tokens,
    }


def merge_pages(results: list[ItemResult], board: ResearchBoard) -> list[SourcePage]:
    """All pages read, de-duplicated by URL in first-read order, capped and trimmed."""
    merged: dict[str, SourcePage] = {}
    for page in [p for r in results for p in r.pages] + board.pages():
        if page.url not in merged:
            merged[page.url] = page
    limit = Config.DEEP_RESEARCH_PAGE_MAX_CHARS
    capped = list(merged.values())[: Config.DEEP_RESEARCH_MAX_PAGES]
    return [SourcePage(p.title, p.url, p.text[:limit]) for p in capped]
