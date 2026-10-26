"""Planner data utilities for fetching and formatting dashboard data.

This module provides functions to fetch Todoist tasks, Google Calendar events,
and weather forecasts for the planner dashboard.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
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
    dashboard_from_dict,
)
from src.services.planner.todoist import fetch_todoist_dashboard_data
from src.services.planner.weather import daily_weather, fetch_forecast
from src.utils.logging import get_logger

logger = get_logger(__name__)


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


def build_planner_dashboard(  # noqa: C901, PLR0912, PLR0915
    todoist_token: str | None = None,
    calendar_token: str | None = None,
    garmin_token: str | None = None,
    user_id: str | None = None,
    force_refresh: bool = False,
    db: Any = None,
) -> PlannerDashboard:
    """Build the complete planner dashboard data with SQLite caching.

    Fetches data from Todoist, Google Calendar, and weather (if configured)
    and organizes it into a 7-day view. Uses SQLite cache to share data
    across multiple uwsgi workers.

    Args:
        todoist_token: The user's Todoist access token (None if not connected)
        calendar_token: The user's Google Calendar access token (None if not connected)
        garmin_token: The user's serialized Garmin session tokens (None if not connected)
        user_id: The user ID for cache key (required for caching)
        force_refresh: Bypass cache and fetch fresh data (for refresh button)
        db: Database instance for caching (optional)

    Returns:
        PlannerDashboard with all data organized by day
    """

    # Check cache if not forcing refresh
    if not force_refresh and user_id and db:
        cached_data = db.get_cached_dashboard(user_id)
        if cached_data:
            logger.debug("Returning cached dashboard", extra={"user_id": user_id})
            # Convert dict back to PlannerDashboard
            return dashboard_from_dict(cached_data)

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
    server_time = now.isoformat()

    # Initialize 7 days
    days: list[PlannerDay] = []
    for i in range(7):
        day_date = now + timedelta(days=i)
        days.append(
            PlannerDay(
                date=day_date.strftime("%Y-%m-%d"),
                day_name=day_name(day_date, now),
            )
        )

    # Create a date-to-day mapping for quick lookup
    date_to_day: dict[str, PlannerDay] = {day.date: day for day in days}

    # Initialize result
    dashboard = PlannerDashboard(
        days=days,
        todoist_connected=bool(todoist_token),
        calendar_connected=bool(calendar_token),
        garmin_connected=bool(garmin_token),
        weather_connected=bool(Config.WEATHER_LOCATION),
        server_time=server_time,
    )

    # Fetch all dashboard resources in parallel (Todoist, Calendar, Garmin, Weather)
    def fetch_todoist_if_available() -> tuple[list[Any], list[Any], str | None]:
        """Fetch Todoist data if token available."""
        if todoist_token:
            return fetch_todoist_dashboard_data(todoist_token)
        return [], [], None

    def fetch_calendar_if_available() -> tuple[list[PlannerEvent], str | None]:
        """Fetch Google Calendar data if token available."""
        try:
            if calendar_token:
                # Get user's selected calendar IDs
                selected_calendar_ids = ["primary"]  # Default
                if user_id and db:
                    try:
                        current_user = db.get_user_by_id(user_id)
                        if current_user and current_user.google_calendar_selected_ids:
                            selected_calendar_ids = current_user.google_calendar_selected_ids
                    except Exception as e:  # falls back to the primary calendar
                        logger.warning(
                            "Failed to get user calendar selection, using primary",
                            extra={"user_id": user_id, "error": str(e)},
                            exc_info=True,
                        )

                return fetch_calendar_dashboard_data(calendar_token, selected_calendar_ids)
            return [], None
        finally:
            _close_thread_pool_connections(db)

    def fetch_weather_if_available() -> tuple[Any | None, str | None]:
        """Fetch weather data if location configured."""
        try:
            return fetch_forecast(db, force_refresh)
        finally:
            _close_thread_pool_connections(db)

    # Fetch all resources in parallel
    with ThreadPoolExecutor(max_workers=4) as executor:
        todoist_future = executor.submit(fetch_todoist_if_available)
        calendar_future = executor.submit(fetch_calendar_if_available)
        garmin_future = executor.submit(fetch_health_summary, garmin_token)
        weather_future = executor.submit(fetch_weather_if_available)

        # Wait for all results
        tasks_7_days, overdue_tasks, todoist_error = todoist_future.result()
        events, calendar_error = calendar_future.result()
        health_summary, garmin_error = garmin_future.result()
        forecast, weather_error = weather_future.result()

    # Process Garmin data
    dashboard.health_summary = health_summary
    dashboard.garmin_error = garmin_error

    # Process Todoist data
    dashboard.overdue_tasks = overdue_tasks
    dashboard.todoist_error = todoist_error

    for task in tasks_7_days:
        if task.due_date and task.due_date in date_to_day:
            date_to_day[task.due_date].tasks.append(task)
        elif not task.due_date:
            # Tasks without due dates go to "Today"
            days[0].tasks.append(task)

    # Process Google Calendar data
    dashboard.calendar_error = calendar_error

    for event in events:
        # For multi-day events (all-day events spanning multiple days),
        # add the event to every day it occurs
        if event.is_all_day and event.start_date and event.end_date:
            start_dt = parse_date(event.start_date)
            # Google Calendar's end_date is exclusive (the day after the event ends)
            end_dt = parse_date(event.end_date)

            if start_dt and end_dt:
                # Add event to each day it spans (end_date is exclusive)
                current_dt = start_dt
                while current_dt < end_dt:
                    event_date = current_dt.strftime("%Y-%m-%d")
                    if event_date in date_to_day:
                        date_to_day[event_date].events.append(event)
                    current_dt += timedelta(days=1)
                continue

        # Regular events (single day or timed events)
        if event.start_date:
            event_date = event.start_date
        elif event.start:
            parsed = parse_datetime(event.start)
            if parsed:
                event_date = parsed.strftime("%Y-%m-%d")
            else:
                continue
        else:
            continue

        if event_date in date_to_day:
            date_to_day[event_date].events.append(event)

    # Process Weather data
    if forecast:
        dashboard.weather_location = forecast.location
        for date_key, weather in daily_weather(forecast).items():
            if date_key in date_to_day:
                date_to_day[date_key].weather = weather
    elif weather_error:
        dashboard.weather_error = weather_error
    elif Config.WEATHER_LOCATION:
        dashboard.weather_error = "Unable to fetch weather data"

    # Sort tasks by priority (highest first) and events by time
    for day in days:
        day.tasks.sort(key=lambda t: -t.priority)
        day.events.sort(key=lambda e: e.start or e.start_date or "")

    logger.info(
        "Planner dashboard built",
        extra={
            "total_events": sum(len(d.events) for d in days),
            "total_tasks": sum(len(d.tasks) for d in days),
            "overdue_tasks": len(dashboard.overdue_tasks),
        },
    )

    # Cache the result if user_id and db provided
    if user_id and db:
        dashboard_dict = asdict(dashboard)
        db.cache_dashboard(user_id, dashboard_dict, ttl_seconds=Config.DASHBOARD_CACHE_TTL_SECONDS)
        logger.debug("Dashboard cached", extra={"user_id": user_id})

    return dashboard
