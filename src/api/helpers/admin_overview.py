"""The admin page's overview (S12), assembled from read-only aggregates.

Names and numbers only: no conversation titles or content ever leave here.
"""

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from flask import current_app

from src.config import Config
from src.db.models import db
from src.utils.costs import convert_currency, format_cost
from src.utils.search_provider import degraded_today, quota_status

SPEND_CHART_DAYS = 30
RECENT_WINDOW = timedelta(days=7)
BROWSER_ERRORS_SHOWN = 15
STACK_FRAMES_SHOWN = 6  # the message line and five frames
RECENT_FAILURES_SHOWN = 5
# scripts/backup_databases.py writes backups/<database file name>/
_BACKUP_DIR_NAME = "backups"


def money(usd: float) -> dict[str, Any]:
    """An amount as USD plus its display-currency text."""
    currency = Config.COST_CURRENCY
    return {
        "usd": round(usd, 6),
        "formatted": format_cost(convert_currency(usd, currency), currency),
    }


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _shares(amounts: dict[str, float]) -> list[dict[str, Any]]:
    ordered = sorted(amounts.items(), key=lambda item: item[1], reverse=True)
    return [{"name": name, "amount": money(usd)} for name, usd in ordered]


def _spend(now: datetime) -> dict[str, Any]:
    today = _day_start(now)
    month = today.replace(day=1)
    users = db.admin_spend_per_user(today, month)
    chart_start = today - timedelta(days=SPEND_CHART_DAYS - 1)
    by_day = dict(db.admin_spend_by_day(chart_start))
    days = [(chart_start + timedelta(days=i)).date().isoformat() for i in range(SPEND_CHART_DAYS)]
    return {
        "today": money(sum(u["today_usd"] for u in users)),
        "month": money(sum(u["month_usd"] for u in users)),
        "threshold": money(Config.SPEND_WARNING_DAILY_USD),
        "users": [
            {
                "name": u["name"],
                "today": money(u["today_usd"]),
                "month": money(u["month_usd"]),
                "month_chats": u["month_chats"],
                "month_turns": u["month_turns"],
                "over_threshold": u["today_usd"] > Config.SPEND_WARNING_DAILY_USD,
            }
            for u in users
        ],
        "daily": [{"date": day, "amount": money(by_day.get(day, 0.0))} for day in days],
        "by_feature": _shares(db.admin_spend_by_feature(month)),
        "by_model": _shares(db.admin_spend_by_model(month)),
    }


def _agents(now: datetime) -> dict[str, Any]:
    runs = db.admin_agent_runs(now - RECENT_WINDOW)
    return {
        "runs_7d": runs["runs"],
        "failed_7d": runs["failed"],
        "pending_approvals": runs["pending_approvals"],
        "recent_failures": [
            {**failure, "started_at": local_time(failure["started_at"]) or ""}
            for failure in db.admin_recent_agent_failures(RECENT_FAILURES_SHOWN)
        ],
    }


def percentile(sorted_values: list[int], fraction: float) -> int | None:
    """Nearest-rank percentile of an ascending list (None when empty)."""
    if not sorted_values:
        return None
    rank = max(1, math.ceil(len(sorted_values) * fraction))
    return sorted_values[rank - 1]


def local_time(stored_utc: str | None) -> str | None:
    """A UTC-naive stored timestamp (agent runs) as local ISO time."""
    if not stored_utc:
        return None
    moment = datetime.fromisoformat(stored_utc).replace(tzinfo=UTC).astimezone()
    return moment.replace(tzinfo=None).isoformat(timespec="seconds")


def _quality(now: datetime) -> dict[str, Any]:
    stats = db.admin_turn_stats(now - RECENT_WINDOW)
    durations = sorted(stats["durations_ms"])
    turns = stats["turns"]
    return {
        "turns_7d": turns,
        "median_ms": percentile(durations, 0.5),
        "p95_ms": percentile(durations, 0.95),
        "tool_error_rate": round(stats["turns_with_tool_errors"] / turns, 4) if turns else 0.0,
    }


def _size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _last_backup_at(database: Path) -> str | None:
    backups = database.parent / _BACKUP_DIR_NAME / database.name
    files = list(backups.glob("*.db")) if backups.is_dir() else []
    if not files:
        return None
    newest = max(file.stat().st_mtime for file in files)
    return datetime.fromtimestamp(newest).isoformat(timespec="seconds")


def _system() -> dict[str, Any]:
    return {
        "version": current_app.config.get("APP_VERSION"),
        "database_bytes": _size(Config.DATABASE_PATH),
        "files_bytes": _size(Config.BLOB_STORAGE_PATH),
        "last_backup_at": _last_backup_at(Config.DATABASE_PATH),
        "latest_migration": db.admin_latest_migration(),
        "users": db.admin_user_count(),
    }


def _browser_errors(now: datetime) -> list[dict[str, Any]]:
    errors = db.top_client_errors(now - RECENT_WINDOW, limit=BROWSER_ERRORS_SHOWN)
    for error in errors:
        error.pop("fingerprint")
        if error["stack"]:
            error["stack"] = "\n".join(error["stack"].splitlines()[:STACK_FRAMES_SHOWN])
    return errors


def build_overview(now: datetime | None = None) -> dict[str, Any]:
    """The whole admin page payload. `now` is a test seam."""
    now = now or datetime.now()
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "currency": Config.COST_CURRENCY,
        "spend": _spend(now),
        "agents": _agents(now),
        "search": {"degraded_today": degraded_today(), "providers": quota_status()},
        "quality": _quality(now),
        "system": _system(),
        "browser_errors": _browser_errors(now),
    }


def spend_status(user_id: str, now: datetime | None = None) -> dict[str, Any]:
    """One user's spend today against the warning threshold (the banner)."""
    today = db.user_spend_since(user_id, _day_start(now or datetime.now()))
    return {
        "today": money(today),
        "threshold_usd": Config.SPEND_WARNING_DAILY_USD,
        "over_threshold": today > Config.SPEND_WARNING_DAILY_USD,
    }
