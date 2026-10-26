"""Planner dashboard assembly: fetch every source in parallel, lay the results
out over the next 7 days, and cache the dashboard in SQLite.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from src.config import Config
from src.services.planner.dates import day_name, parse_date, parse_datetime
from src.services.planner.garmin import fetch_health_summary
from src.services.planner.google_calendar import fetch_calendar_dashboard_data
from src.services.planner.models import (
    PlannerDashboard,
    PlannerDay,
    PlannerEvent,
    PlannerHealthSummary,
    PlannerTask,
    dashboard_from_dict,
)
from src.services.planner.todoist import fetch_todoist_dashboard_data
from src.services.planner.weather import daily_weather, fetch_forecast
from src.utils.logging import get_logger
from src.utils.weather import WeatherForecast

logger = get_logger(__name__)


@dataclass
class _SourceData:
    """What the four parallel fetches returned."""

    tasks: list[PlannerTask]
    overdue_tasks: list[PlannerTask]
    todoist_error: str | None
    events: list[PlannerEvent]
    calendar_error: str | None
    health_summary: PlannerHealthSummary | None
    garmin_error: str | None
    forecast: WeatherForecast | None
    weather_error: str | None


def _close_thread_pool_connections(db: Any = None) -> None:
    """Close DB pool connections for the current thread.

    Called in finally blocks of ThreadPoolExecutor workers so that the
    ConnectionPool doesn't keep a reference to the connection after the
    worker thread exits.
    """
    if db is not None:
        try:
            db._pool.close_thread_connection()
        except Exception:
            logger.debug("Thread-local db connection close failed", exc_info=True)


def _fetch_todoist(todoist_token: str | None) -> tuple[list[Any], list[Any], str | None]:
    if todoist_token:
        return fetch_todoist_dashboard_data(todoist_token)
    return [], [], None


def _selected_calendar_ids(user_id: str | None, db: Any) -> list[str]:
    """The user's selected calendars, or just the primary one."""
    if user_id and db:
        try:
            current_user = db.get_user_by_id(user_id)
            if current_user and current_user.google_calendar_selected_ids:
                selected: list[str] = current_user.google_calendar_selected_ids
                return selected
        except Exception as e:  # falls back to the primary calendar
            logger.warning(
                "Failed to get user calendar selection, using primary",
                extra={"user_id": user_id, "error": str(e)},
                exc_info=True,
            )
    return ["primary"]


def _fetch_calendar(
    calendar_token: str | None, user_id: str | None, db: Any
) -> tuple[list[PlannerEvent], str | None]:
    try:
        if calendar_token:
            calendar_ids = _selected_calendar_ids(user_id, db)
            return fetch_calendar_dashboard_data(calendar_token, calendar_ids)
        return [], None
    finally:
        _close_thread_pool_connections(db)


def _fetch_weather(db: Any, force_refresh: bool) -> tuple[WeatherForecast | None, str | None]:
    try:
        return fetch_forecast(db, force_refresh)
    finally:
        _close_thread_pool_connections(db)


def _fetch_sources(
    todoist_token: str | None,
    calendar_token: str | None,
    garmin_token: str | None,
    user_id: str | None,
    force_refresh: bool,
    db: Any,
) -> _SourceData:
    """Fetch Todoist, Calendar, Garmin and weather in parallel."""
    with ThreadPoolExecutor(max_workers=4) as executor:
        todoist_future = executor.submit(_fetch_todoist, todoist_token)
        calendar_future = executor.submit(_fetch_calendar, calendar_token, user_id, db)
        garmin_future = executor.submit(fetch_health_summary, garmin_token)
        weather_future = executor.submit(_fetch_weather, db, force_refresh)

        tasks, overdue_tasks, todoist_error = todoist_future.result()
        events, calendar_error = calendar_future.result()
        health_summary, garmin_error = garmin_future.result()
        forecast, weather_error = weather_future.result()

    return _SourceData(
        tasks=tasks,
        overdue_tasks=overdue_tasks,
        todoist_error=todoist_error,
        events=events,
        calendar_error=calendar_error,
        health_summary=health_summary,
        garmin_error=garmin_error,
        forecast=forecast,
        weather_error=weather_error,
    )


def _empty_days(now: datetime) -> list[PlannerDay]:
    """Seven days starting today."""
    days = []
    for i in range(7):
        day_date = now + timedelta(days=i)
        days.append(
            PlannerDay(date=day_date.strftime("%Y-%m-%d"), day_name=day_name(day_date, now))
        )
    return days


def _place_tasks(days: list[PlannerDay], tasks: list[PlannerTask]) -> None:
    """Put each task on its due day; tasks without a due date go to today."""
    date_to_day = {day.date: day for day in days}
    for task in tasks:
        if task.due_date and task.due_date in date_to_day:
            date_to_day[task.due_date].tasks.append(task)
        elif not task.due_date:
            days[0].tasks.append(task)


def _event_dates(event: PlannerEvent) -> list[str]:
    """The dates an event falls on; an all-day event covers every day it spans."""
    if event.is_all_day and event.start_date and event.end_date:
        start_dt = parse_date(event.start_date)
        # Google Calendar's end_date is exclusive (the day after the event ends)
        end_dt = parse_date(event.end_date)
        if start_dt and end_dt:
            span = (end_dt - start_dt).days
            return [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(span)]

    if event.start_date:
        return [event.start_date]
    parsed = parse_datetime(event.start)
    return [parsed.strftime("%Y-%m-%d")] if parsed else []


def _place_events(days: list[PlannerDay], events: list[PlannerEvent]) -> None:
    date_to_day = {day.date: day for day in days}
    for event in events:
        for event_date in _event_dates(event):
            if event_date in date_to_day:
                date_to_day[event_date].events.append(event)


def _apply_weather(dashboard: PlannerDashboard, sources: _SourceData) -> None:
    if sources.forecast:
        dashboard.weather_location = sources.forecast.location
        date_to_day = {day.date: day for day in dashboard.days}
        for date_key, weather in daily_weather(sources.forecast).items():
            if date_key in date_to_day:
                date_to_day[date_key].weather = weather
    elif sources.weather_error:
        dashboard.weather_error = sources.weather_error
    elif Config.WEATHER_LOCATION:
        dashboard.weather_error = "Unable to fetch weather data"


def _apply_sources(dashboard: PlannerDashboard, sources: _SourceData) -> None:
    """Lay the fetched data out over the dashboard's days."""
    dashboard.health_summary = sources.health_summary
    dashboard.garmin_error = sources.garmin_error
    dashboard.overdue_tasks = sources.overdue_tasks
    dashboard.todoist_error = sources.todoist_error
    dashboard.calendar_error = sources.calendar_error
    _place_tasks(dashboard.days, sources.tasks)
    _place_events(dashboard.days, sources.events)
    _apply_weather(dashboard, sources)

    # Sort tasks by priority (highest first) and events by time
    for day in dashboard.days:
        day.tasks.sort(key=lambda t: -t.priority)
        day.events.sort(key=lambda e: e.start or e.start_date or "")

    logger.info(
        "Planner dashboard built",
        extra={
            "total_events": sum(len(d.events) for d in dashboard.days),
            "total_tasks": sum(len(d.tasks) for d in dashboard.days),
            "overdue_tasks": len(dashboard.overdue_tasks),
        },
    )


def _cache_dashboard(dashboard: PlannerDashboard, user_id: str | None, db: Any) -> None:
    if user_id and db:
        db.cache_dashboard(
            user_id, asdict(dashboard), ttl_seconds=Config.DASHBOARD_CACHE_TTL_SECONDS
        )
        logger.debug("Dashboard cached", extra={"user_id": user_id})


def _cached_dashboard(user_id: str | None, db: Any) -> PlannerDashboard | None:
    if not (user_id and db):
        return None
    cached_data = db.get_cached_dashboard(user_id)
    if not cached_data:
        return None
    logger.debug("Returning cached dashboard", extra={"user_id": user_id})
    return dashboard_from_dict(cached_data)


def build_planner_dashboard(
    todoist_token: str | None = None,
    calendar_token: str | None = None,
    garmin_token: str | None = None,
    user_id: str | None = None,
    force_refresh: bool = False,
    db: Any = None,
) -> PlannerDashboard:
    """Build the 7-day planner dashboard, served from the SQLite cache when fresh.

    The cache (keyed by ``user_id``, needs ``db``) is shared by all workers;
    ``force_refresh`` bypasses it (the refresh button). A token of None means
    that integration isn't connected; weather needs Config.WEATHER_LOCATION.
    """
    cached = None if force_refresh else _cached_dashboard(user_id, db)
    if cached:
        return cached

    logger.debug(
        "Building fresh planner dashboard",
        extra={
            "todoist_connected": bool(todoist_token),
            "calendar_connected": bool(calendar_token),
            "garmin_connected": bool(garmin_token),
            "weather_configured": bool(Config.WEATHER_LOCATION),
            "force_refresh": force_refresh,
        },
    )
    now = datetime.now()
    dashboard = PlannerDashboard(
        days=_empty_days(now),
        todoist_connected=bool(todoist_token),
        calendar_connected=bool(calendar_token),
        garmin_connected=bool(garmin_token),
        weather_connected=bool(Config.WEATHER_LOCATION),
        server_time=now.isoformat(),
    )
    sources = _fetch_sources(
        todoist_token, calendar_token, garmin_token, user_id, force_refresh, db
    )
    _apply_sources(dashboard, sources)
    _cache_dashboard(dashboard, user_id, db)
    return dashboard
