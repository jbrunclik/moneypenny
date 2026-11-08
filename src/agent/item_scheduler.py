"""The every-minute scheduler's pass over items set from chat.

One-offs (reminder, check-in) fire without a model call and are deleted;
one more than SCHEDULE_MISSED_GRACE_HOURS late (scheduler downtime, or a chat
restored from the trash after the time) is not fired late but noted as
missed. Watchers and recurring items run (src/agent/item_runner.py): a
silent run backs a watcher off, a report is delivered, [DONE] ends a watcher,
SCHEDULE_ITEM_MAX_FAILURES failures in a row stop the item, and an item past
its end stops with a note in its chat. Each item is handled on its own: one
bad item never stops the tick.

Standing jobs (grants set: an agent's schedule) have looser limits: no expiry,
any cron (in the job's timezone), no slow-down; they wait while an approval
they asked for is pending, skip a run over their daily budget (not a failure),
and after the failure limit pause with one alert instead of being deleted.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from src.agent.item_runner import RunOutcome, RunTrigger, deliver, delivery_label, run_model_item
from src.agent.tools.scheduling import watch_expiry
from src.config import Config
from src.db.models import db
from src.db.models.scheduled_items import NEVER_RUN_AT
from src.services.push import send_push_to_user
from src.utils.clock import utc_now
from src.utils.logging import get_logger
from src.utils.schedule_spec import describe_instant, next_cron_run

if TYPE_CHECKING:
    from src.db.models import User
    from src.db.models.dataclasses import ScheduledItem

logger = get_logger(__name__)

WATCH_MAX_INTERVAL_HOURS = 168
_ONE_OFFS = {"reminder", "check_in"}
# Patched in tests: the tick's elapsed time for SCHEDULE_TICK_BUDGET_SECONDS
_monotonic = time.monotonic
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
    """Handle every item due by `now`; returns what was done.

    One-offs (a push, no model call) go first. No model run starts once the
    tick has used SCHEDULE_TICK_BUDGET_SECONDS - the scheduler process is
    killed a little later - so the rest wait for the next tick, unchanged.
    """
    result = ItemsResult()
    db.reset_stale_runs(now, Config.SCHEDULE_RUN_STALE_MINUTES)
    claimed = sorted(db.claim_due_items(now), key=lambda i: i.kind not in _ONE_OFFS)
    started = _monotonic()
    for item in claimed:
        if (
            item.kind not in _ONE_OFFS
            and _monotonic() - started > Config.SCHEDULE_TICK_BUDGET_SECONDS
        ):
            db.finish_item_run(
                item.id,
                item.next_run_at,
                item.last_result,
                item.quiet_runs,
                item.failures,
                claimed_at=item.claimed_at,
            )
            continue
        try:
            _handle(item, now, result)
        except Exception:  # one bad item must not stop the others
            logger.exception("Scheduled item failed", extra={"item_id": item.id})
            _recover(item, now)
    return result


def _recover(item: ScheduledItem, now: datetime) -> None:
    """Give a failed item back; a second error is logged, never raised (the
    agents run after this pass in the same tick)."""
    try:
        _give_back(item, now, failed=True)
    except Exception:  # the stale reset picks it up later
        logger.exception("Scheduled item recovery failed", extra={"item_id": item.id})


def _handle(item: ScheduledItem, now: datetime, result: ItemsResult) -> None:
    if item.kind in {"reminder", "check_in"}:
        _fire_one_off(item, now, result)
        return
    expiry = None if item.standing else watch_expiry(item)
    if expiry is not None and expiry <= now:
        _stop(item, now, _expired_text(item))
        result.expired += 1
        return
    user = db.get_user_by_id(item.user_id)
    if user is None:
        db.delete_item(item.id)
        return
    if item.standing and _job_held(item, now):
        return
    result.run += 1
    _apply_outcome(item, now, run_model_item(item, user))


class JobBusyError(Exception):
    """The job is running already (the scheduler or another hand-started run)."""


class JobHeldError(Exception):
    """The job must not run now (waiting for an approval, over its budget);
    the message says why."""


def run_job_now(
    item: ScheduledItem,
    user: User,
    *,
    message: str | None = None,
    trigger: RunTrigger = "manual",
    trigger_chain: list[str] | None = None,
) -> RunOutcome:
    """Run a standing job now - by hand (Run, resuming after an approval) or
    triggered by another agent - and post its report; no failure counting.
    A hand-started run does not push (the user is in the app).

    The job is claimed for the run like a due one, so the scheduler (or a
    second tap) cannot run it at the same time - writes would happen twice.
    Raises JobBusyError when it is running already.
    """
    if (reason := hold_reason(item)) is not None:
        raise JobHeldError(reason)
    claim = db.claim_item(item.id, utc_now())
    if claim is None:
        raise JobBusyError(item.id)
    prior_status, claimed_at = claim
    try:
        outcome = run_model_item(
            item, user, trigger=trigger, message=message, trigger_chain=trigger_chain
        )
        if outcome.status in {"report", "done"} and outcome.text:
            tag = "run now" if trigger == "manual" else "triggered"
            label = delivery_label(item.kind, utc_now(), Config.APP_TIMEZONE, tag)
            deliver(item, outcome.text, label, push=trigger != "manual", outcome=outcome)
    finally:
        db.release_item(item.id, claimed_at, prior_status)
    return outcome


def hold_reason(item: ScheduledItem) -> str | None:
    """Why a standing job must not run now, by any path: it waits for an
    approval it asked for, or it spent its daily budget."""
    if db.has_pending_approval(item.id):
        return "waiting for your approval"
    budget = item.budget_usd
    if budget is not None and budget > 0 and db.job_spend_today(item.id) >= budget:
        return f"over its daily budget (${budget:.2f})"
    return None


def _job_held(item: ScheduledItem, now: datetime) -> bool:
    """A held standing job is given back on its schedule; an over-budget one
    records a skipped run (not a failure)."""
    reason = hold_reason(item)
    if reason is None:
        return False
    if "budget" in reason:
        execution = db.create_execution(item.id, "scheduled")
        db.update_execution(execution.id, "failed", f"Skipped: {reason}")
        logger.info("Standing job over budget", extra={"item_id": item.id})
    _give_back(item, now, failed=False)
    return True


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
        if item.failures + 1 < Config.SCHEDULE_ITEM_MAX_FAILURES:
            _give_back(item, now, failed=True)
        elif item.standing:
            _pause_job(item, now, outcome.error or "unknown error")
        else:
            _stop(item, now, f"{_stopped_title(item)} - kept failing: {item.text}")
        return
    found = outcome.status == "done" and item.kind == "watcher"
    if outcome.status == "silent" or (not outcome.text and not found):  # nothing to tell
        _finish(item, now, item.last_result, item.quiet_runs + 1)
        return
    if not _may_deliver(item, now, outcome):
        return
    if found:
        # A bare [DONE] still says what was found (the watcher is gone after this)
        text = outcome.text or f"Found: {item.end_condition} ({item.text})"
        deliver(item, text, delivery_label(item.kind, now, tz, "found"), outcome=outcome)
        db.delete_item(item.id)
        return
    tag = "update" if item.kind == "watcher" else None
    deliver(item, outcome.text, delivery_label(item.kind, now, tz, tag), outcome=outcome)
    _finish(item, now, outcome.text, 0)


def _may_deliver(item: ScheduledItem, now: datetime, outcome: RunOutcome) -> bool:
    """A result reaches the chat only while the item's claim holds and its chat
    is live: one cancelled mid-run, or whose chat was trashed or archived
    meanwhile, is dropped (its cost still recorded); a suspended item waits."""
    state = db.item_claim_state(item.id, item.claimed_at)
    if state == "live":
        return True
    if outcome.record_cost is not None:
        outcome.record_cost(f"silent:{uuid.uuid4()}")
    if state == "suspended":
        _finish(item, now, item.last_result, item.quiet_runs)
    logger.info("Scheduled item result dropped", extra={"item_id": item.id, "state": state})
    return False


def _next_run(item: ScheduledItem, now: datetime, quiet_runs: int) -> datetime:
    if item.standing and not item.schedule:  # runs only by hand or when triggered
        return NEVER_RUN_AT
    if item.kind == "recurring" and item.schedule:
        nxt = next_cron_run(item.schedule, item.timezone or Config.APP_TIMEZONE, now)
    else:
        nxt = next_watch_run(
            now, item.interval_hours or 24, quiet_runs, item.expires_at is not None
        )
    expiry = None if item.standing else watch_expiry(item)
    return min(nxt, expiry) if expiry is not None else nxt


def _finish(item: ScheduledItem, now: datetime, last_result: str | None, quiet_runs: int) -> None:
    db.finish_item_run(
        item.id,
        _next_run(item, now, quiet_runs),
        last_result,
        quiet_runs,
        0,
        claimed_at=item.claimed_at,
    )


def _give_back(item: ScheduledItem, now: datetime, failed: bool) -> None:
    """Back to the scheduler on its normal interval (a one-off is dropped)."""
    if item.kind in {"reminder", "check_in"}:
        db.delete_item(item.id)
        return
    failures = item.failures + 1 if failed else item.failures
    db.finish_item_run(
        item.id,
        _next_run(item, now, item.quiet_runs),
        item.last_result,
        item.quiet_runs,
        failures,
        claimed_at=item.claimed_at,
    )


def _stopped_title(item: ScheduledItem) -> str:
    return "Stopped watching" if item.kind == "watcher" else "Stopped"


def _expired_text(item: ScheduledItem) -> str:
    if item.kind == "watcher":
        return f'Stopped watching: {item.text} - no "{item.end_condition}" within its time.'
    return f"Stopped: reached its end date - {item.text}"


def _pause_job(item: ScheduledItem, now: datetime, error: str) -> None:
    """A standing job that kept failing pauses - one alert, one push - and keeps
    its setup; the user resumes it from the chat's schedule chip."""
    failures = item.failures + 1
    text = (
        f"Paused after {failures} failed runs: {error[:_PUSH_BODY_CHARS]}. "
        "Resume it from the chat's schedule chip."
    )
    deliver(item, text, delivery_label(item.kind, now, Config.APP_TIMEZONE, "paused"))
    db.finish_item_run(
        item.id,
        _next_run(item, now, item.quiet_runs),
        item.last_result,
        item.quiet_runs,
        failures,
        claimed_at=item.claimed_at,
    )
    db.set_item_paused(item.id, item.user_id, True, reason="failures")
    logger.warning("Standing job paused after failures", extra={"item_id": item.id})


def _stop(item: ScheduledItem, now: datetime, text: str) -> None:
    deliver(item, text, delivery_label(item.kind, now, Config.APP_TIMEZONE, "stopped"), push=False)
    db.delete_item(item.id)
