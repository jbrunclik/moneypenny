"""The eval worker pool (evals/pool.py)."""

from typing import Any

import pytest

import evals.pool as pool


def test_each_case_gets_a_fresh_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """A timed-out case leaves its thread running inside its fakes' patches;
    a worker that took the next case would inherit them (live web, stray
    writes in the next case's actions). One case per worker process ends it."""
    seen: dict[str, Any] = {}

    class RecordingPool:
        def __init__(self, **kwargs: Any) -> None:
            seen.update(kwargs)

        def submit(self, fn: Any, case: Any) -> Any:
            from concurrent.futures import Future

            future: Future[Any] = Future()
            future.set_result({"id": case.id})
            return future

        def shutdown(self, **kwargs: Any) -> None:
            pass

    monkeypatch.setattr(pool, "ProcessPoolExecutor", RecordingPool)
    case = pool.EvalCase(id="a", description="", user="u")
    results: list[dict[str, Any]] = []
    pool.run_cases([case], 4, results.append)
    assert seen["max_tasks_per_child"] == 1
    assert results == [{"id": "a"}]
