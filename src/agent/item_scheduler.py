"""The every-minute scheduler's pass over items set from chat.

One-offs (reminder, check-in) fire without a model call and are deleted;
one more than SCHEDULE_MISSED_GRACE_HOURS late (scheduler downtime, or a chat
restored from the trash after the time) is not fired late but noted as
missed. Watchers and recurring items run (src/agent/item_runner.py): a
silent run backs a watcher off, a report is delivered, [DONE] ends a watcher,
SCHEDULE_ITEM_MAX_FAILURES failures in a row stop the item (one push, the
only alert of its failures), and an item past
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
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from src.agent.item_runner import RunOutcome, RunTrigger, deliver, delivery_label, run_model_item
from src.agent.tools.scheduling import watch_expiry
from src.agent.turn_budget import run_time_budget
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
# A continuation after cards that failed: told once in its chat, not retried
_CONTINUATION_FAILED = (
    "I could not continue after your answer ({}). Run me again from the agent's page "
    "if it still needs doing."
)
_CONTINUATION_ERROR_CHARS = 160
# Patched in tests: the pass's elapsed time against SCHEDULE_TICK_DEADLINE_SECONDS
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

    One-offs (a push, no model call) go first, then continuations after
    cards (the user is waiting on them), then due runs. The pass must end by
    SCHEDULE_TICK_DEADLINE_SECONDS (systemd kills it at 300 s): each model
    run gets the time left as its budget (_run_budget_s), so it stops on
    time with its wrap-up instead of being killed and replayed; one with too
    little time left waits for the next pass, unchanged.
    """
    result = ItemsResult()
    db.reset_stale_runs(now, Config.SCHEDULE_RUN_STALE_MINUTES)
    claimed = sorted(
        db.claim_due_items(now),
        key=lambda i: (i.kind not in _ONE_OFFS, i.resume_message is None),
    )
    started = _monotonic()
    for item in claimed:
        budget = None
        if item.kind not in _ONE_OFFS:
            budget = _run_budget_s(started, _monotonic())
            if budget is None and item.resume_message is not None:
                # Off-schedule: back exactly as it was, continuation kept
                db.release_item(item.id, item.claimed_at or now, item.status)
                continue
            if budget is None:
                db.finish_item_run(
                    item.id,
                    item.next_run_at,
                    item.last_result,
                    item.quiet_runs,
                    item.failures,
                    claimed_at=item.claimed_at,
                )
                continue
            if budget < Config.TURN_TIME_BUDGET_SECONDS:
                logger.info(
                    "Run budget capped by the scheduler pass",
                    extra={"item_id": item.id, "budget_s": round(budget)},
                )
        try:
            with run_time_budget(budget) if budget is not None else nullcontext():
                _handle(item, now, result)
        except Exception:  # one bad item must not stop the others
            logger.exception("Scheduled item failed", extra={"item_id": item.id})
            _recover(item, now)
    return result


def _run_budget_s(started: float, now_mono: float) -> float | None:
    """A model run's time budget at ``now_mono`` in a pass begun at
    ``started``; None when too little is left to start one."""
    left = (
        Config.SCHEDULE_TICK_DEADLINE_SECONDS
        - (now_mono - started)
        - Config.SCHEDULE_RUN_FINISH_MARGIN_SECONDS
    )
    if left < Config.SCHEDULE_MIN_RUN_SECONDS:
        return None
    return min(float(Config.TURN_TIME_BUDGET_SECONDS), left)


def _recover(item: ScheduledItem, now: datetime) -> None:
    """Give a failed item back; a second error is logged, never raised (the
    agents run after this pass in the same tick)."""
    try:
        _give_back(item, now, failed=True)
    except Exception:  # the stale reset picks it up later
        logger.exception("Scheduled item recovery failed", extra={"item_id": item.id})


def _handle(item: ScheduledItem, now: datetime, result: ItemsResult) -> None:
    if item.resume_message is not None:
        _continue_after_cards(item, now, result)
        return
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
    if _job_held(item, now):
        return
    result.run += 1
    _apply_outcome(item, now, run_model_item(item, user))


class JobBusyError(Exception):
    """The job is running already (the scheduler or another hand-started run)."""


class JobHeldError(Exception):
    """The job must not run now (waiting for an approval, over its budget);
    the message says why."""


# How a report from an off-schedule run is labelled
_DELIVERY_TAGS: dict[str, str] = {"manual": "run now", "approval": "after your answer"}


def run_job_now(
    item: ScheduledItem,
    user: User,
    *,
    message: str | None = None,
    trigger: RunTrigger = "manual",
    trigger_chain: list[str] | None = None,
) -> RunOutcome:
    """Run a standing job now - by hand (Run) or triggered by another agent -
    and post its report; no failure counting. A hand-started run does not
    push (the user is in the app). A run continuing after its cards goes
    through the scheduler instead (_continue_after_cards).

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
        return _run_off_schedule(item, user, trigger, message, claimed_at, trigger_chain)
    finally:
        db.release_item(item.id, claimed_at, prior_status)


def _run_off_schedule(
    item: ScheduledItem,
    user: User,
    trigger: RunTrigger,
    message: str | None,
    claimed_at: datetime,
    trigger_chain: list[str] | None = None,
) -> RunOutcome:
    """Run a claimed job outside its schedule and post its report (pushed
    unless the user started it by hand) - not into a chat trashed or archived
    during the run (its cost is still recorded, as for a scheduled run)."""
    outcome = run_model_item(
        item, user, trigger=trigger, message=message, trigger_chain=trigger_chain
    )
    if not (outcome.status in {"report", "done"} and outcome.text):
        return outcome
    if db.item_claim_state(item.id, claimed_at) != "live":
        if outcome.record_cost is not None:
            outcome.record_cost(f"silent:{uuid.uuid4()}")
        logger.info("Off-schedule result dropped", extra={"item_id": item.id})
        return outcome
    tag = _DELIVERY_TAGS.get(trigger, "triggered")
    label = delivery_label(item.kind, utc_now(), Config.APP_TIMEZONE, tag)
    deliver(item, outcome.text, label, push=trigger != "manual", outcome=outcome)
    return outcome


def _continue_after_cards(item: ScheduledItem, now: datetime, result: ItemsResult) -> None:
    """A job whose cards were answered: run its continuation with their
    outcome, at most once, then give it back exactly as it was (status and
    schedule). Held (another card, its budget) it keeps the message for a
    later pass; one that fails is not retried - its chat says so (a retry
    every pass cost a model run each time, final review Nov 15 2026)."""
    claimed_at = item.claimed_at or now  # this pass claimed it at `now`
    prior = item.status  # claim_due_items: the status it was claimed from
    requested = item.resume_requested_at
    waited_s = round((now - requested).total_seconds()) if requested else None
    user = db.get_user_by_id(item.user_id)
    if user is None:
        db.delete_item(item.id)
        return
    if (reason := hold_reason(item)) is not None:
        if waited_s is None or waited_s // 60 % 60 == 0:  # about hourly, not every pass
            logger.info(
                "Run continuation held",
                extra={"item_id": item.id, "reason": reason, "waited_s": waited_s},
            )
        db.release_item(item.id, claimed_at, prior)
        return
    logger.info("Run resumed after cards", extra={"item_id": item.id, "waited_s": waited_s})
    result.run += 1
    db.clear_resume(item.id)
    try:
        outcome = _run_off_schedule(item, user, "approval", item.resume_message, claimed_at)
        failure = outcome.text or "the run failed" if outcome.status == "failed" else None
    except Exception as error:  # given back below, never retried
        logger.exception("Run continuation crashed", extra={"item_id": item.id})
        failure = str(error)[:_CONTINUATION_ERROR_CHARS]
    if failure is not None and db.item_claim_state(item.id, claimed_at) == "live":
        label = delivery_label(item.kind, utc_now(), Config.APP_TIMEZONE, "after your answer")
        deliver(item, _CONTINUATION_FAILED.format(failure), label)
    db.release_item(item.id, claimed_at, prior)


def daily_budget(item: ScheduledItem) -> float:
    """The item's daily budget: its own, else UNATTENDED_DAILY_BUDGET_USD (the
    Daily Briefing, older jobs and the light items had none - Nov 17 2026)."""
    own = item.budget_usd
    return own if own is not None and own > 0 else Config.UNATTENDED_DAILY_BUDGET_USD


def hold_reason(item: ScheduledItem) -> str | None:
    """Why a scheduled item must not run now, by any path: it waits for an
    approval it asked for, or it spent its daily budget."""
    if db.has_pending_run_proposal(item.id):
        return "waiting for your approval"
    budget = daily_budget(item)
    if db.job_spend_today(item.id) >= budget:
        return f"over its daily budget (${budget:.2f})"
    return None


def _job_held(item: ScheduledItem, now: datetime) -> bool:
    """A held item is given back on its schedule; an over-budget one
    records a skipped run (not a failure)."""
    reason = hold_reason(item)
    if reason is None:
        return False
    if "budget" in reason:
        execution = db.create_execution(item.id, "scheduled")
        db.update_execution(execution.id, "failed", f"Skipped: {reason}")
        logger.info(
            "Scheduled item over budget",
            extra={"item_id": item.id, "kind": item.kind, "budget_usd": daily_budget(item)},
        )
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
            _stop(item, now, f"{_stopped_title(item)} - kept failing: {item.text}", push=True)
            logger.warning(
                "Scheduled item stopped after failures",
                extra={"item_id": item.id, "kind": item.kind, "error": (outcome.error or "")[:200]},
            )
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


def _stop(item: ScheduledItem, now: datetime, text: str, push: bool = False) -> None:
    """Ends a light item with a note in its chat. Reaching its end is expected
    and quiet; one stopped for failing pushes once (its only alert: failed
    runs before it push nothing), or it would vanish unnoticed."""
    label = delivery_label(item.kind, now, Config.APP_TIMEZONE, "stopped")
    deliver(item, text, label, push=push)
    db.delete_item(item.id)
