"""Unit tests for the deploy health gate (scripts/deploy_health_gate.py).

Oct 13 2026: the old gate curled /api/health right after `systemctl reload`
and passed against the OLD workers, while the new ones crash-looped. The gate
must see the workers replaced, the service not restarted, and several healthy
probes in a row.
"""

from collections.abc import Iterator

from scripts.deploy_health_gate import Snapshot, wait_for_new_workers

BEFORE = Snapshot(main_pid=100, restarts=0, worker_pids=frozenset({101, 102}), healthy=True)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _run(snapshots: list[Snapshot], timeout_s: float = 60) -> tuple[bool, str]:
    clock = FakeClock()
    it: Iterator[Snapshot] = iter(snapshots)
    last = snapshots[-1]
    return wait_for_new_workers(
        BEFORE,
        probe=lambda: next(it, last),
        timeout_s=timeout_s,
        interval_s=2,
        required_ok=3,
        clock=clock.time,
        sleep=clock.sleep,
    )


def test_old_workers_answering_is_not_healthy() -> None:
    # The Oct 13 case: health passes, but only because the old workers answer
    ok, message = _run([BEFORE], timeout_s=20)
    assert not ok
    assert "timed out" in message


def test_new_workers_healthy_three_times_in_a_row() -> None:
    new = Snapshot(main_pid=100, restarts=0, worker_pids=frozenset({201, 202}), healthy=True)
    ok, _ = _run([BEFORE, new, new, new])
    assert ok


def test_a_failed_probe_resets_the_streak() -> None:
    new_ok = Snapshot(main_pid=100, restarts=0, worker_pids=frozenset({201}), healthy=True)
    new_bad = Snapshot(main_pid=100, restarts=0, worker_pids=frozenset({201}), healthy=False)
    clock_runs = [new_ok, new_ok, new_bad, new_ok, new_ok]
    ok, _ = _run(clock_runs, timeout_s=9)
    assert not ok


def test_service_restart_fails_fast() -> None:
    # Workers failed to boot -> master exited -> systemd restarted it
    crashed = Snapshot(main_pid=300, restarts=1, worker_pids=frozenset({301}), healthy=True)
    ok, message = _run([crashed, crashed, crashed, crashed])
    assert not ok
    assert "restarted" in message


def test_service_down_fails_fast() -> None:
    down = Snapshot(main_pid=0, restarts=0, worker_pids=frozenset(), healthy=False)
    ok, message = _run([down])
    assert not ok
    assert "restarted" in message or "not running" in message
