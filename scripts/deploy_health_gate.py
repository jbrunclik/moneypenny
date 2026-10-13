#!/usr/bin/env python3
"""Reload the app service and wait until the NEW workers are healthy.

`systemctl reload` sends HUP: gunicorn boots new workers while the old ones
keep serving, so a health check right after the reload passes against the old
workers even when the new ones fail to boot (Oct 13 2026: "Deploy healthy."
was printed, then the master gave up and the service crash-looped). This gate
passes only once every old worker is gone, the service has not restarted, and
the health URL answered several times in a row.

Usage (from `make update`):
    python scripts/deploy_health_gate.py --unit moneypenny --url http://localhost:8000/api/health
"""

import argparse
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_INTERVAL_SECONDS = 2
DEFAULT_REQUIRED_OK = 3
HEALTH_REQUEST_TIMEOUT_SECONDS = 3


@dataclass(frozen=True)
class Snapshot:
    """The service as seen at one moment."""

    main_pid: int
    restarts: int
    worker_pids: frozenset[int]
    healthy: bool


def wait_for_new_workers(
    before: Snapshot,
    probe: Callable[[], Snapshot],
    timeout_s: float = DEFAULT_TIMEOUT_SECONDS,
    interval_s: float = DEFAULT_INTERVAL_SECONDS,
    required_ok: int = DEFAULT_REQUIRED_OK,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, str]:
    """Poll until all workers are new and healthy `required_ok` times in a row.

    Fails fast when the service restarted or stopped (new workers failed to
    boot, so the master exited). Returns (ok, message).
    """
    deadline = clock() + timeout_s
    streak = 0
    while clock() <= deadline:
        now = probe()
        if now.main_pid == 0:
            return False, "service not running - new workers failed to boot?"
        if now.main_pid != before.main_pid or now.restarts != before.restarts:
            return False, "service restarted - new workers failed to boot?"
        replaced = bool(now.worker_pids) and not (now.worker_pids & before.worker_pids)
        streak = streak + 1 if replaced and now.healthy else 0
        if streak >= required_ok:
            return True, f"{len(now.worker_pids)} new workers healthy"
        sleep(interval_s)
    return False, f"timed out after {timeout_s:.0f}s waiting for new healthy workers"


def _systemctl_show(unit: str) -> tuple[int, int]:
    out = subprocess.run(
        ["systemctl", "--user", "show", "-p", "MainPID", "-p", "NRestarts", unit],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    values = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return int(values.get("MainPID", "0") or 0), int(values.get("NRestarts", "0") or 0)


def _children(pid: int) -> frozenset[int]:
    if pid == 0:
        return frozenset()
    out = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout
    return frozenset(int(p) for p in out.split())


def _healthy(url: str) -> bool:
    try:
        return httpx.get(url, timeout=HEALTH_REQUEST_TIMEOUT_SECONDS).status_code == 200
    except httpx.HTTPError:
        return False


def snapshot(unit: str, url: str) -> Snapshot:
    main_pid, restarts = _systemctl_show(unit)
    return Snapshot(main_pid, restarts, _children(main_pid), _healthy(url))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--unit", required=True, help="systemd --user unit to reload")
    parser.add_argument("--url", required=True, help="health URL that must answer 200")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args()

    before = snapshot(args.unit, args.url)
    if before.main_pid == 0:
        print(f"{args.unit} is not running - start it first", file=sys.stderr)
        return 1
    subprocess.run(["systemctl", "--user", "reload", args.unit], check=True)
    print("Reload triggered, waiting for new workers (migrations apply on startup)...")
    ok, message = wait_for_new_workers(
        before, lambda: snapshot(args.unit, args.url), timeout_s=args.timeout
    )
    if ok:
        print(f"Deploy healthy. ({message})")
        return 0
    print(f"DEPLOY UNHEALTHY: {message} - check: journalctl --user -u {args.unit} -n 50")
    return 1


if __name__ == "__main__":
    sys.exit(main())
