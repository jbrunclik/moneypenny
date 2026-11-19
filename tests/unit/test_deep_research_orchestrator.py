"""The deep-research orchestrator with fake subagents."""

import threading
import time
from typing import Any

import pytest

from src.agent.cancellation import TurnCancelled, token_for
from src.agent.deep_research import orchestrator as orch
from src.agent.deep_research.board import ResearchBoard
from src.agent.deep_research.briefs import build_brief
from src.agent.deep_research.orchestrator import ItemResult, Orchestrator, merge_pages
from src.agent.deep_research.plan import DeepResearchPlan
from src.agent.source_pages import SourcePage
from src.config import Config


def _plan(n: int) -> DeepResearchPlan:
    items = [f"q{i}" for i in range(n)]
    return DeepResearchPlan(
        "offer-1", "Question?", "Praha", items, items, estimate={"minutes": 5, "cost_czk": 10}
    )


@pytest.fixture(autouse=True)
def _limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "DEEP_RESEARCH_PARALLELISM", 4)
    monkeypatch.setattr(Config, "DEEP_RESEARCH_SUBAGENT_TIMEOUT_SECONDS", 5.0)
    # No room for a gap pass unless a test makes some (the TestGapPass tests)
    monkeypatch.setattr(Config, "DEEP_RESEARCH_GAP_TIMEOUT_SECONDS", 10_000.0)
    orch.reset_slots(8)


def _wait_cancellable(request_id: str, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        token = token_for(request_id)
        if token and token.cancelled:
            raise TurnCancelled
        time.sleep(0.01)  # poll interval for the cancellation


def _ok(brief: str, board: ResearchBoard, index: int, request_id: str) -> ItemResult:
    page = SourcePage(f"P{index}", f"https://p{index}.cz", "text")
    board.record_page(index, page)
    return ItemResult(
        index, "done", f"digest {index}", [page], {"input_tokens": 10, "output_tokens": 2}
    )


def _run(
    plan: DeepResearchPlan, events: list[dict[str, Any]]
) -> tuple[Orchestrator, list[ItemResult]]:
    o = Orchestrator(plan, events.append, run_id="run-1", today="2026-10-03", recent_turns="")
    return o, o.run()


def test_all_done_emits_events_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch, "run_subagent", _ok)
    events: list[dict[str, Any]] = []

    _, results = _run(_plan(3), events)

    assert [r.status for r in results] == ["done", "done", "done"]
    plan_event = events[0]
    # started_at keeps the client's elapsed clock right when a reload replays the journal
    assert isinstance(plan_event.pop("started_at"), int)
    assert plan_event == {"type": "research_plan", "items": ["q0", "q1", "q2"], "minutes": 5}
    done = [e for e in events if e["type"] == "research_item" and e["status"] == "done"]
    assert sorted(e["index"] for e in done) == [0, 1, 2] and all(e["pages"] == 1 for e in done)
    assert events[-1] == {"type": "research_sources", "count": 3}


def test_parallelism_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "DEEP_RESEARCH_PARALLELISM", 2)
    running, peak, lock = [0], [0], threading.Lock()

    def slow(brief: str, board: ResearchBoard, index: int, request_id: str) -> ItemResult:
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.05)  # work long enough for the items to overlap
        with lock:
            running[0] -= 1
        return ItemResult(index, "done", "", [], {})

    monkeypatch.setattr(orch, "run_subagent", slow)
    _run(_plan(4), [])

    assert peak[0] == 2


def test_second_run_waits_for_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    orch.reset_slots(2)
    release = threading.Event()
    started = threading.Semaphore(0)

    def held(brief: str, board: ResearchBoard, index: int, request_id: str) -> ItemResult:
        started.release()
        release.wait(2)
        return ItemResult(index, "done", "", [], {})

    monkeypatch.setattr(orch, "run_subagent", held)
    first_events: list[dict[str, Any]] = []
    second_events: list[dict[str, Any]] = []
    first = threading.Thread(target=lambda: _run(_plan(2), first_events))
    first.start()
    # Both slots taken by the first run before the second starts
    assert started.acquire(timeout=2) and started.acquire(timeout=2)
    second = threading.Thread(target=lambda: _run(_plan(2), second_events))
    second.start()
    deadline = time.monotonic() + 2
    while not any(e.get("status") == "waiting" for e in second_events):
        assert time.monotonic() < deadline, "the second run never waited for a slot"
        time.sleep(0.01)  # poll interval
    release.set()
    first.join(3)
    second.join(3)
    assert sum(1 for e in second_events if e.get("status") == "done") == 2


def test_an_item_past_its_deadline_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "DEEP_RESEARCH_SUBAGENT_TIMEOUT_SECONDS", 0.2)

    def maybe_slow(brief: str, board: ResearchBoard, index: int, request_id: str) -> ItemResult:
        if index == 1:
            board.record_page(1, SourcePage("partial", "https://partial.cz", "half"))
            _wait_cancellable(request_id, 5)
        return ItemResult(index, "done", "", [], {})

    monkeypatch.setattr(orch, "run_subagent", maybe_slow)
    _o, results = _run(_plan(2), [])

    assert [r.status for r in results] == ["done", "timed_out"]
    assert [p.url for p in results[1].pages] == ["https://partial.cz"]


def _blocked_in_a_tool(release: threading.Event) -> object:
    """A subagent stuck inside one tool call: it never checks its cancel token."""

    def run(brief: str, board: ResearchBoard, index: int, request_id: str) -> ItemResult:
        if index == 1:
            board.record_page(1, SourcePage("partial", "https://partial.cz", "half"))
            release.wait(10)
        return ItemResult(index, "done", "", [], {})

    return run


def test_a_subagent_blocked_in_a_tool_cannot_hold_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "DEEP_RESEARCH_SUBAGENT_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(Config, "DEEP_RESEARCH_CUT_GRACE_SECONDS", 0.2)
    release = threading.Event()
    monkeypatch.setattr(orch, "run_subagent", _blocked_in_a_tool(release))
    started = time.monotonic()
    try:
        _, results = _run(_plan(2), [])
    finally:
        release.set()

    assert time.monotonic() - started < 2
    assert [r.status for r in results] == ["done", "timed_out"]
    assert [p.url for p in results[1].pages] == ["https://partial.cz"]


def test_finish_now_does_not_wait_for_a_blocked_subagent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "DEEP_RESEARCH_CUT_GRACE_SECONDS", 0.2)
    release = threading.Event()
    monkeypatch.setattr(orch, "run_subagent", _blocked_in_a_tool(release))
    o = Orchestrator(_plan(2), lambda e: None, run_id="run-2", today="2026-10-03", recent_turns="")
    threading.Timer(0.2, o.finish_now).start()
    started = time.monotonic()
    try:
        results = o.run()
    finally:
        release.set()

    assert time.monotonic() - started < 2
    assert [r.status for r in results] == ["done", "skipped"]


def test_failures_are_recorded_per_item(monkeypatch: pytest.MonkeyPatch) -> None:
    def flaky(brief: str, board: ResearchBoard, index: int, request_id: str) -> ItemResult:
        if index == 0:
            raise RuntimeError("search down")
        return ItemResult(index, "done", "", [], {})

    monkeypatch.setattr(orch, "run_subagent", flaky)

    _, results = _run(_plan(2), [])

    assert [r.status for r in results] == ["failed", "done"]


def test_finish_now_skips_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "DEEP_RESEARCH_PARALLELISM", 1)

    def slow(brief: str, board: ResearchBoard, index: int, request_id: str) -> ItemResult:
        _wait_cancellable(request_id, 0.3)
        return ItemResult(index, "done", "", [], {})

    monkeypatch.setattr(orch, "run_subagent", slow)
    o = Orchestrator(_plan(3), lambda e: None, run_id="run-2", today="2026-10-03", recent_turns="")
    threading.Timer(0.1, o.finish_now).start()

    results = o.run()

    assert results[0].status == "skipped"  # cut while running
    assert [r.status for r in results[1:]] == ["skipped", "skipped"]  # never started


def test_stop_raises_turn_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(brief: str, board: ResearchBoard, index: int, request_id: str) -> ItemResult:
        _wait_cancellable(request_id, 3)
        return ItemResult(index, "done", "", [], {})

    monkeypatch.setattr(orch, "run_subagent", slow)
    o = Orchestrator(_plan(2), lambda e: None, run_id="run-3", today="2026-10-03", recent_turns="")
    threading.Timer(0.1, o.stop).start()

    with pytest.raises(TurnCancelled):
        o.run()


def test_merge_pages_dedupes_caps_and_keeps_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "DEEP_RESEARCH_MAX_PAGES", 3)
    monkeypatch.setattr(Config, "DEEP_RESEARCH_PAGE_MAX_CHARS", 4)
    board = ResearchBoard()
    a, b, c, d = (SourcePage(n, f"https://{n}.cz", "long text") for n in "abcd")
    results = [ItemResult(0, "done", "", [a, b], {}), ItemResult(1, "done", "", [b, c, d], {})]

    merged = merge_pages(results, board)

    assert [p.url for p in merged] == ["https://a.cz", "https://b.cz", "https://c.cz"]
    assert merged[0].text == "long"


def test_merge_pages_keeps_every_sub_questions_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nov 19 2026: sub-questions 1 and 2 read 22 + 21 pages, so a first-40 cut
    dropped all of the price question's shop pages - the report stated its
    prices from the digest and the check flagged them as unsourced."""
    monkeypatch.setattr(Config, "DEEP_RESEARCH_MAX_PAGES", 40)
    board = ResearchBoard()

    def pages(tag: str, n: int) -> list[SourcePage]:
        return [SourcePage(f"{tag}{i}", f"https://{tag}{i}.cz", "t") for i in range(n)]

    results = [
        ItemResult(0, "done", "", pages("fit", 22), {}),
        ItemResult(1, "done", "", pages("anc", 21), {}),
        ItemResult(2, "done", "", pages("shop", 12), {}),
    ]

    merged = merge_pages(results, board)

    assert len(merged) == 40
    per_item = {tag: sum(p.title.startswith(tag) for p in merged) for tag in ("fit", "anc", "shop")}
    assert per_item["shop"] == 12  # all of the small one's pages
    assert per_item["fit"] >= 13 and per_item["anc"] >= 13
    # Each sub-question's own pages keep their reading order
    assert [p.title for p in merged if p.title.startswith("shop")] == [
        f"shop{i}" for i in range(12)
    ]


def test_brief_carries_context_date_and_previous_report() -> None:
    plan = _plan(2)
    plan.previous_report = "Round 1 found X."

    brief = build_brief(plan, 1, today="2026-10-03", recent_turns="user asked about agencies")

    for part in ("Question?", "Praha", "2026-10-03", "q1", "Round 1 found X.", "share_finding"):
        assert part in brief


def test_a_cut_subagent_keeps_what_it_spent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deadline cuts are routine: their tokens must still be priced."""
    from langchain_core.messages import AIMessage

    from src.agent.turn_usage import record_model_usage

    monkeypatch.setattr(Config, "DEEP_RESEARCH_SUBAGENT_TIMEOUT_SECONDS", 0.2)
    usage = {"input_tokens": 400, "output_tokens": 40, "total_tokens": 440}

    def spends_then_hangs(
        brief: str, board: ResearchBoard, index: int, request_id: str
    ) -> ItemResult:
        record_model_usage(AIMessage(content="", usage_metadata=usage))
        if index == 1:
            _wait_cancellable(request_id, 5)
        return ItemResult(index, "done", "", [], {})

    monkeypatch.setattr(orch, "run_subagent", spends_then_hangs)
    o, results = _run(_plan(2), [])

    assert [r.status for r in results] == ["done", "timed_out"]
    assert [u["input_tokens"] for u in o.spent()] == [400, 400]
    assert results[1].usage["input_tokens"] == 400


class TestGapPass:
    """Nov 17 2026: one wave then the writer - a failed, timed-out or thin
    item got no second try even with minutes of the estimate left."""

    @pytest.fixture(autouse=True)
    def _room(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Config, "DEEP_RESEARCH_GAP_TIMEOUT_SECONDS", 2.0)
        monkeypatch.setattr(Config, "DEEP_RESEARCH_GAP_MIN_PAGES", 2)

    def test_failed_and_thin_items_get_one_more_subagent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        briefs: dict[int, list[str]] = {0: [], 1: [], 2: []}

        def first_fails(brief: str, board: ResearchBoard, index: int, rid: str) -> ItemResult:
            briefs[index].append(brief)
            attempt = len(briefs[index])
            if index == 0 and attempt == 1:
                raise RuntimeError("search down")
            pages = [SourcePage(f"P{index}-{attempt}", f"https://p{index}-{attempt}.cz", "t")]
            if index == 2:  # plenty on the first try: no retry
                pages.append(SourcePage("X", "https://x.cz", "t"))
            for page in pages:
                board.record_page(index, page)
            return ItemResult(index, "done", f"d{index}-{attempt}", pages, {"input_tokens": 5})

        monkeypatch.setattr(orch, "run_subagent", first_fails)
        events: list[dict[str, Any]] = []

        _, results = _run(_plan(3), events)

        assert [len(briefs[i]) for i in range(3)] == [2, 2, 1]
        assert "failed with an error" in briefs[0][1]
        assert "found too little" in briefs[1][1] and "https://p1-1.cz" in briefs[1][1]
        assert [r.status for r in results] == ["done", "done", "done"]
        thin = results[1]
        assert [p.url for p in thin.pages] == ["https://p1-1.cz", "https://p1-2.cz"]
        assert thin.digest == "d1-1\n\nd1-2"
        assert events[-1] == {"type": "research_sources", "count": 5}

    def test_no_retry_without_time_left(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Config, "DEEP_RESEARCH_GAP_TIMEOUT_SECONDS", 10_000.0)
        calls: list[int] = []

        def thin(brief: str, board: ResearchBoard, index: int, rid: str) -> ItemResult:
            calls.append(index)
            return ItemResult(index, "done", "d", [], {})

        monkeypatch.setattr(orch, "run_subagent", thin)
        _run(_plan(2), [])
        assert sorted(calls) == [0, 1]

    def test_no_retry_after_finish_now(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[int] = []
        holder: list[Orchestrator] = []

        def thin(brief: str, board: ResearchBoard, index: int, rid: str) -> ItemResult:
            calls.append(index)
            holder[0].finish_now()
            return ItemResult(index, "done", "d", [], {})

        monkeypatch.setattr(orch, "run_subagent", thin)
        o = Orchestrator(_plan(1), [].append, run_id="run-1", today="2026-10-03", recent_turns="")
        holder.append(o)
        o.run()
        assert calls == [0]


def test_merged_attempts_keep_both_and_sum_the_spend() -> None:
    from src.agent.deep_research.orchestrator import merge_attempts

    a = SourcePage("A", "https://a.cz", "t")
    b = SourcePage("B", "https://b.cz", "t")
    first = ItemResult(0, "timed_out", "", [a], {"input_tokens": 7, "output_tokens": 1})
    retry = ItemResult(0, "done", "found it", [a, b], {"input_tokens": 3})

    merged = merge_attempts(first, retry)

    assert (merged.status, merged.digest) == ("done", "found it")
    assert [p.url for p in merged.pages] == ["https://a.cz", "https://b.cz"]
    assert merged.usage == {"input_tokens": 10, "output_tokens": 1}
    # A retry that fails keeps the first attempt's done status
    kept = merge_attempts(ItemResult(0, "done", "x", [a], {}), ItemResult(0, "failed", "", [], {}))
    assert kept.status == "done"
