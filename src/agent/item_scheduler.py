"""The every-minute scheduler's pass over items set from chat.

One-offs (reminder, check-in) fire without a model call and are deleted;
one more than SCHEDULE_MISSED_GRACE_HOURS late (scheduler downtime, or a chat
restored from the trash after the time) is not fired late but noted as
missed. Watchers and recurring items run (src/agent/item_runner.py): a
silent run backs a watcher off, a report is delivered, [DONE] ends a watcher,
SCHEDULE_ITEM_MAX_FAILURES failures in a row stop the item, and an item past
its end stops with a note in its chat. Each item is handled on its own: one
bad item never stops the tick.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from src.agent.item_runner import RunOutcome, deliver, delivery_label, run_model_item
from src.agent.tools.scheduling import watch_expiry
from src.config import Config
from src.db.models import db
from src.services.push import send_push_to_user
from src.utils.logging import get_logger
from src.utils.schedule_spec import describe_instant, next_cron_run

if TYPE_CHECKING:
    from src.db.models.dataclasses import ScheduledItem

logger = get_logger(__name__)

WATCH_MAX_INTERVAL_HOURS = 168
_PUSH_BODY_CHARS = 160


@dataclass
class ItemsResult:
    """What one tick did with items."""

    fired: int = 0
    run: int = 0
    missed: int = 0
    expired: int = 0


def next_watch_run(
    now: datetime, interval_hours: int, quiet_runs: int, has_until: bool
) -> datetime:
    """The next check: the interval doubles per SCHEDULE_WATCH_SLOWDOWN_AFTER_RUNS quiet
    runs in a row, up to weekly - except for a watcher with a user-given end date."""
    hours = interval_hours
    if not has_until:
        hours = min(
            interval_hours * 2 ** (quiet_runs // Config.SCHEDULE_WATCH_SLOWDOWN_AFTER_RUNS),
            WATCH_MAX_INTERVAL_HOURS,
        )
    return now + timedelta(hours=hours)


def run_due_items(now: datetime) -> ItemsResult:
    """Handle every item due by `now`; returns what was done."""
    result = ItemsResult()
    db.reset_stale_runs(now, Config.SCHEDULE_RUN_STALE_MINUTES)
    for item in db.claim_due_items(now):
        try:
            _handle(item, now, result)
        except Exception:  # one bad item must not stop the others
            logger.exception("Scheduled item failed", extra={"item_id": item.id})
            _give_back(item, now, failed=True)
    return result


def _handle(item: ScheduledItem, now: datetime, result: ItemsResult) -> None:
    if item.kind in {"reminder", "check_in"}:
        _fire_one_off(item, now, result)
        return
    expiry = watch_expiry(item)
    if expiry is not None and expiry <= now:
        _stop(item, now, _expired_text(item))
        result.expired += 1
        return
    user = db.get_user_by_id(item.user_id)
    if user is None:
        db.delete_item(item.id)
        return
    result.run += 1
    _apply_outcome(item, now, run_model_item(item, user))


def _fire_one_off(item: ScheduledItem, now: datetime, result: ItemsResult) -> None:
    tz = Config.APP_TIMEZONE
    if now - item.next_run_at > timedelta(hours=Config.SCHEDULE_MISSED_GRACE_HOURS):
        text = f"Missed (was due {describe_instant(item.next_run_at, tz)}): {item.text}"
        deliver(item, text, delivery_label(item.kind, now, tz, "missed"), push=False)
        result.missed += 1
    elif item.kind == "reminder":
        send_push_to_user(
            item.user_id,
            "Reminder",
            item.text[:_PUSH_BODY_CHARS],
            url=f"/#/conversations/{item.conversation_id}",
            tag=f"item-{item.id}",
        )
        result.fired += 1
    else:
        deliver(item, item.text, delivery_label(item.kind, item.next_run_at, tz))
        result.fired += 1
    db.delete_item(item.id)


def _apply_outcome(item: ScheduledItem, now: datetime, outcome: RunOutcome) -> None:
    tz = Config.APP_TIMEZONE
    if outcome.status == "failed":
        if item.failures + 1 >= Config.SCHEDULE_ITEM_MAX_FAILURES:
            _stop(item, now, f"{_stopped_title(item)} - kept failing: {item.text}")
        else:
            _give_back(item, now, failed=True)
        return
    if outcome.status == "silent":
        _finish(item, now, item.last_result, item.quiet_runs + 1)
        return
    if outcome.status == "done" and item.kind == "watcher":
        deliver(item, outcome.text, delivery_label(item.kind, now, tz, "found"), outcome=outcome)
        db.delete_item(item.id)
        return
    tag = "update" if item.kind == "watcher" else None
    deliver(item, outcome.text, delivery_label(item.kind, now, tz, tag), outcome=outcome)
    _finish(item, now, outcome.text, 0)


def _next_run(item: ScheduledItem, now: datetime, quiet_runs: int) -> datetime:
    if item.kind == "recurring" and item.schedule:
        nxt = next_cron_run(item.schedule, Config.APP_TIMEZONE, now)
    else:
        nxt = next_watch_run(
            now, item.interval_hours or 24, quiet_runs, item.expires_at is not None
        )
    expiry = watch_expiry(item)
    return min(nxt, expiry) if expiry is not None else nxt


def _finish(item: ScheduledItem, now: datetime, last_result: str | None, quiet_runs: int) -> None:
    db.finish_item_run(
        item.id, _next_run(item, now, quiet_runs), last_result, quiet_runs, failures=0
    )


def _give_back(item: ScheduledItem, now: datetime, failed: bool) -> None:
    """Back to the scheduler on its normal interval (a one-off is dropped)."""
    if item.kind in {"reminder", "check_in"}:
        db.delete_item(item.id)
        return
    failures = item.failures + 1 if failed else item.failures
    db.finish_item_run(
        item.id, _next_run(item, now, item.quiet_runs), item.last_result, item.quiet_runs, failures
    )


def _stopped_title(item: ScheduledItem) -> str:
    return "Stopped watching" if item.kind == "watcher" else "Stopped"


def _expired_text(item: ScheduledItem) -> str:
    if item.kind == "watcher":
        return f'Stopped watching: {item.text} - no "{item.end_condition}" within its time.'
    return f"Stopped: reached its end date - {item.text}"


def _stop(item: ScheduledItem, now: datetime, text: str) -> None:
    deliver(item, text, delivery_label(item.kind, now, Config.APP_TIMEZONE, "stopped"), push=False)
    db.delete_item(item.id)
