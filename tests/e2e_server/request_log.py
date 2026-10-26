"""The SLOW/INFLIGHT phase log: slow and still-running requests on stderr."""

import sys
import threading
import time

from flask import Flask, g, request


def register_request_log(app: Flask) -> None:
    """Time every request; resolve_db adds its phases to `g._phases`."""
    # Slow-request log: any request the mock server takes >1s to answer is
    # a starvation suspect (the suite's flakes are "mock response never
    # arrived" timeouts). Printed to stderr so it shows up in Playwright's
    # [WebServer] output; grep for SLOW.

    # In-flight watchdog: a request that is still running after 3s is
    # printed while it hangs (INFLIGHT ...), so a stall that never finishes
    # before the run ends still shows up in the log with its path/phase.
    _inflight: dict[int, tuple[float, str, str]] = {}
    _inflight_lock = threading.Lock()

    def _watchdog() -> None:
        while True:
            time.sleep(1.0)  # the watchdog's tick - nothing to poll for
            now = time.perf_counter()
            with _inflight_lock:
                stuck = [
                    (now - t0, m, path) for t0, m, path in _inflight.values() if now - t0 > 3.0
                ]
            for age, method, path in stuck:
                print(
                    f"INFLIGHT {age:.1f}s {method} {path} threads={threading.active_count()}",
                    file=sys.stderr,
                    flush=True,
                )

    threading.Thread(target=_watchdog, name="inflight-watchdog", daemon=True).start()

    @app.before_request
    def _mark_request_start() -> None:
        g._req_start = time.perf_counter()
        with _inflight_lock:
            _inflight[threading.get_ident()] = (g._req_start, request.method, request.path)

    @app.teardown_request
    def _clear_inflight(_exc: BaseException | None) -> None:
        with _inflight_lock:
            _inflight.pop(threading.get_ident(), None)

    @app.after_request
    def _log_slow_request(response):  # type: ignore[no-untyped-def]
        start = getattr(g, "_req_start", None)
        if start is not None and not response.is_streamed:
            elapsed = time.perf_counter() - start
            if elapsed > 1.0:
                phases = " ".join(f"{k}={v:.2f}" for k, v in getattr(g, "_phases", {}).items())
                print(
                    f"SLOW {elapsed:.2f}s {request.method} {request.path} "
                    f"test={request.headers.get('X-Test-Execution-Id', '-')[:8]} "
                    f"threads={threading.active_count()} {phases}",
                    file=sys.stderr,
                    flush=True,
                )
        return response
