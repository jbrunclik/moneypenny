"""Development scheduler for autonomous agents.

In development mode, this module runs a background thread that evaluates
agent schedules periodically (every minute) and triggers due agents.

This replaces the systemd timer used in production. Both use the same
core logic from src/agent/scheduler.py.
"""

from __future__ import annotations

import threading

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Global reference to the scheduler thread
_scheduler_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None

# How often to check schedules (in seconds)
SCHEDULER_INTERVAL_SECONDS = 60


def _scheduler_loop(stop_event: threading.Event) -> None:
    """Main scheduler loop that runs in a background thread."""
    from src.agent.scheduler import run_scheduled_agents

    logger.info("Dev scheduler: starting background loop")

    while not stop_event.is_set():
        try:
            run_scheduled_agents()
        except Exception as e:
            logger.error(f"Dev scheduler: error in evaluation loop: {e}", exc_info=True)

        # Wait for the interval or until stopped
        stop_event.wait(SCHEDULER_INTERVAL_SECONDS)

    logger.info("Dev scheduler: background loop stopped")


def start_dev_scheduler() -> None:
    """Start the development scheduler if in development mode.

    This function is safe to call multiple times - it will only start
    the scheduler once.
    """
    global _scheduler_thread, _stop_event

    # Only run in development mode
    if not Config.is_development():
        return

    # Don't start if already running
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        logger.debug("Dev scheduler: already running")
        return

    logger.info("Dev scheduler: initializing for development mode")

    _stop_event = threading.Event()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        args=(_stop_event,),
        daemon=True,  # Dies when main thread exits
        name="DevAgentScheduler",
    )
    _scheduler_thread.start()

    logger.info("Dev scheduler: started")


def stop_dev_scheduler() -> None:
    """Stop the development scheduler if running."""
    global _scheduler_thread, _stop_event

    if _stop_event is not None:
        logger.info("Dev scheduler: stopping")
        _stop_event.set()

    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        _scheduler_thread.join(timeout=5)

    _scheduler_thread = None
    _stop_event = None

    logger.info("Dev scheduler: stopped")
