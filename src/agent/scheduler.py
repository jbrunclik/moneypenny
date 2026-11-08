"""Shared scheduler logic: the every-minute pass.

Used by both:
- Production: systemd timer script (scripts/run_agent_scheduler.py)
- Development: background thread (src/agent/dev_scheduler.py)

Agents are standing jobs since standing chats phase 2 (migration 0080), so
one pass over scheduled items (src/agent/item_scheduler.py) runs reminders,
check-ins, watchers, recurring items and agents alike.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.agent.item_scheduler import run_due_items
from src.db.models import db
from src.utils.clock import utc_now
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SchedulerResult:
    """Result of a scheduler run."""

    items_fired: int = 0  # reminders and check-ins sent
    items_run: int = 0  # watcher, recurring and standing-job runs


def run_scheduled_agents() -> SchedulerResult:
    """Run everything due: one pass over scheduled items (agents included)."""
    now = utc_now()

    # Clean up zombie executions (stuck in running/waiting_approval for too long)
    zombies_cleaned = db.cleanup_zombie_executions()
    if zombies_cleaned > 0:
        logger.warning("Scheduler: cleaned up zombie executions", extra={"count": zombies_cleaned})

    items = run_due_items(now)
    result = SchedulerResult(items_fired=items.fired, items_run=items.run)
    logger.info(
        "Scheduler: completed",
        extra={
            "items_fired": result.items_fired,
            "items_run": result.items_run,
            "items_missed": items.missed,
            "items_expired": items.expired,
        },
    )
    return result
