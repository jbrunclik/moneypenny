"""Parallel eval execution: cases run on a pool of worker processes.

Processes, not threads: fake_integrations patches module attributes
process-wide, and seeded memories and past conversations belong to the one
eval user, so cases sharing a process would see each other's state. Each
worker owns an isolated temp database (isolate_environment before its first
src import) and runs its cases one at a time, like the sequential runner.

"spawn", never "fork": a forked worker would inherit the parent's db
singleton, already bound to the parent's database.
"""

import multiprocessing
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

from evals.run import EvalCase, execute_case, isolate_environment

_worker: dict[str, Any] = {}


def _init_worker() -> None:
    isolate_environment()
    from src.db.models import db

    _worker["db"] = db
    _worker["user"] = db.get_or_create_user("eval@example.com", "Eval User")


def _run_in_worker(case: EvalCase) -> dict[str, Any]:
    return execute_case(case, _worker["user"], _worker["db"])


def run_cases(
    cases: list[EvalCase], workers: int, on_result: Callable[[dict[str, Any]], None]
) -> None:
    """Run every case, calling on_result (in this process) as each finishes."""
    if not cases:
        return
    pool = ProcessPoolExecutor(
        max_workers=min(workers, len(cases)),
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_init_worker,
    )
    futures = {pool.submit(_run_in_worker, case): case for case in cases}
    try:
        for future in as_completed(futures):
            case = futures[future]
            try:
                result = future.result()
            except Exception as e:  # a dead worker fails its case, not the run
                result = {"id": case.id, "pass": False, "score": 0, "error": f"worker: {e}"}
            on_result(result)
    finally:
        # Ctrl-C: drop the queued cases instead of paying for them
        pool.shutdown(wait=True, cancel_futures=True)
