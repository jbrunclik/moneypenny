"""A retried deep research reuses the sub-questions an interrupted run finished.

Nov 17 2026: a deploy kills a running research; Retry reopened the offer and
paid for every subagent again. Finished items are now saved as they finish
and a run of the same offer reuses them.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest

from src.agent.deep_research import item_store
from src.agent.deep_research import orchestrator as orch
from src.agent.deep_research.board import ResearchBoard
from src.agent.deep_research.orchestrator import ItemResult, Orchestrator
from src.agent.deep_research.plan import DeepResearchPlan
from src.agent.source_pages import SourcePage
from src.agent.tools.context import set_conversation_context
from src.config import Config

if TYPE_CHECKING:
    from src.db.models import Database, User


@pytest.fixture(autouse=True)
def _setup(
    test_database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    monkeypatch.setattr(item_store, "db", test_database)
    monkeypatch.setattr(Config, "DEEP_RESEARCH_GAP_TIMEOUT_SECONDS", 10_000.0)  # no gap pass
    orch.reset_slots(8)
    set_conversation_context("conv-1", test_user.id)
    yield
    set_conversation_context(None, None)


def _plan(items: list[str]) -> DeepResearchPlan:
    return DeepResearchPlan("offer-msg-1", "Q?", "", items, items, estimate={"minutes": 5})


def _run(plan: DeepResearchPlan) -> list[ItemResult]:
    return Orchestrator(plan, [].append, run_id="r", today="2026-11-17", recent_turns="").run()


def test_a_retry_runs_only_what_the_first_run_did_not_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    fail = {1}

    def subagent(brief: str, board: ResearchBoard, index: int, rid: str) -> ItemResult:
        calls.append(index)
        if index in fail:
            raise RuntimeError("deploy killed it")
        page = SourcePage(f"P{index}", f"https://p{index}.cz", "x" * 50)
        return ItemResult(index, "done", f"digest {index}", [page], {})

    monkeypatch.setattr(orch, "run_subagent", subagent)
    first = _run(_plan(["q0", "q1"]))
    assert [r.status for r in first] == ["done", "failed"]

    calls.clear()
    fail.clear()
    retry = _run(_plan(["q0", "q1", "q2 (added on reopen)"]))

    assert sorted(calls) == [1, 2]
    assert [r.status for r in retry] == ["done", "done", "done"]
    assert retry[0].digest == "digest 0"
    assert [p.url for p in retry[0].pages] == ["https://p0.cz"]


def test_only_finished_items_are_kept(test_user: User) -> None:
    for status in ("failed", "timed_out", "skipped"):
        item_store.save_item(test_user.id, "offer", "q", ItemResult(0, status, "d", [], {}))  # type: ignore[arg-type]
    assert item_store.load_item(test_user.id, "offer", "q", 0) is None


def test_another_offer_does_not_reuse(test_user: User) -> None:
    item_store.save_item(test_user.id, "offer-a", "q", ItemResult(0, "done", "d", [], {}))
    assert item_store.load_item(test_user.id, "offer-b", "q", 3) is None
    reused = item_store.load_item(test_user.id, "offer-a", "q", 3)
    assert reused is not None and reused.index == 3


def test_page_text_is_kept_only_as_far_as_the_writer_reads(
    test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Config, "DEEP_RESEARCH_PAGE_MAX_CHARS", 10)
    page = SourcePage("T", "https://t.cz", "y" * 100)
    item_store.save_item(test_user.id, "o", "q", ItemResult(0, "done", "d", [page], {}))
    loaded = item_store.load_item(test_user.id, "o", "q", 0)
    assert loaded is not None and loaded.pages[0].text == "y" * 10
