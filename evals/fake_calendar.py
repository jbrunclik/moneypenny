"""In-memory Google Calendar for eval cases (the tool's HTTP seam, not the tool).

google_calendar is one of production's most used integrations and had no
eval coverage. A case opts in with ``integrations: {calendar: ...}``:

    calendar:
      state: connected            # or: not_connected
      calendars: [{id: rodina@example.com, summary: Rodina, primary: true}]
      events:
        - {id: e1, calendar_id: primary, summary: ..., location?, description?,
           start: {dateTime: "{tomorrow}T16:00:00+01:00"} | {date: "{tomorrow}"},
           end: {...}}

Reads are filtered by the requested range (and ``q``); create / update /
delete are recorded in ``actions`` for the judge and required_actions.
"""

from __future__ import annotations

import contextlib
import copy
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any
from unittest.mock import patch

from src.utils.clock import app_tz

_PRIMARY = "primary"
_TOOL = "src.agent.tools.google_calendar"


def _instant(value: dict[str, Any] | None) -> datetime | None:
    """An event boundary as an aware datetime (an all-day date at local midnight)."""
    if not value:
        return None
    if value.get("dateTime"):
        moment = datetime.fromisoformat(str(value["dateTime"]))  # tz-naive: offset kept, else local
        return moment if moment.tzinfo else moment.replace(tzinfo=app_tz())
    if value.get("date"):
        day = date.fromisoformat(str(value["date"])[:10])
        return datetime(day.year, day.month, day.day, tzinfo=app_tz())
    return None


class FakeCalendar:
    """Just enough of the Calendar REST API for the tool's actions."""

    def __init__(self, fixture: dict[str, Any]) -> None:
        self.calendars: list[dict[str, Any]] = copy.deepcopy(fixture.get("calendars") or [])
        if not self.calendars:
            self.calendars = [{"id": "eval@example.com", "summary": "Eval", "primary": True}]
        self.events: list[dict[str, Any]] = copy.deepcopy(fixture.get("events") or [])
        for event in self.events:
            event.setdefault("calendar_id", _PRIMARY)
            event.setdefault("status", "confirmed")
        self.actions: list[str] = []
        self._next = 100

    def _calendar_events(self, calendar_id: str) -> list[dict[str, Any]]:
        primary = next((c["id"] for c in self.calendars if c.get("primary")), None)
        ids = {calendar_id} | ({_PRIMARY, primary} if calendar_id in (_PRIMARY, primary) else set())
        return [e for e in self.events if e["calendar_id"] in ids]

    def _find(self, calendar_id: str, event_id: str) -> dict[str, Any]:
        for event in self._calendar_events(calendar_id):
            if event["id"] == event_id:
                return event
        raise Exception('Google Calendar API error (404): {"error": {"message": "Not Found"}}')

    def _list(self, calendar_id: str, params: dict[str, Any]) -> dict[str, Any]:
        lo = _instant({"dateTime": params["timeMin"]}) or datetime.max.replace(tzinfo=app_tz())
        hi = _instant({"dateTime": params["timeMax"]}) or lo
        query = str(params.get("q") or "").lower()
        hits = []
        for event in self._calendar_events(calendar_id):
            start, end = _instant(event.get("start")), _instant(event.get("end"))
            if start is None or start >= hi or (end or start) <= lo:
                continue
            if query and query not in f"{event.get('summary')} {event.get('description')}".lower():
                continue
            hits.append(event)
        hits.sort(key=lambda e: _instant(e.get("start")) or lo)
        limit = int(params.get("maxResults") or 250)
        page: dict[str, Any] = {"items": copy.deepcopy(hits[:limit])}
        if len(hits) > limit:
            page["nextPageToken"] = "more"
        return page

    def _create(self, calendar_id: str, data: dict[str, Any]) -> dict[str, Any]:
        self._next += 1
        event = {"id": f"ev{self._next}", "calendar_id": calendar_id, "status": "confirmed"}
        event |= copy.deepcopy(data)
        self.events.append(event)
        when = (data.get("start") or {}).get("dateTime") or (data.get("start") or {}).get("date")
        self.actions.append(f"created event {data.get('summary')!r} {when}")
        return copy.deepcopy(event)

    def api_request(
        self,
        method: str,
        endpoint: str,
        token: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        _retry_on_401: bool = True,
    ) -> dict[str, Any] | None:
        parts = endpoint.strip("/").split("/")
        if endpoint == "/users/me/calendarList" and method == "GET":
            return {"items": copy.deepcopy(self.calendars)}
        if len(parts) == 3 and parts[0] == "calendars" and parts[2] == "events":
            if method == "GET":
                return self._list(parts[1], params or {})
            if method == "POST":
                return self._create(parts[1], data or {})
        if len(parts) == 4 and parts[0] == "calendars" and parts[2] == "events":
            event = self._find(parts[1], parts[3])
            if method == "GET":
                return copy.deepcopy(event)
            if method == "PATCH":
                event.update(copy.deepcopy(data or {}))
                self.actions.append(f"updated event {event.get('summary')!r} {data}")
                return copy.deepcopy(event)
            if method == "DELETE":
                self.events.remove(event)
                self.actions.append(f"deleted event {event.get('summary')!r}")
                return None
        raise ValueError(f"FakeCalendar: unsupported {method} {endpoint}")


@contextlib.contextmanager
def fake_calendar(fixture: dict[str, Any]) -> Iterator[FakeCalendar | None]:
    """Install the Calendar fake (yields None when the fixture is not connected)."""
    connected = (fixture.get("state") or "connected") == "connected"
    fake = FakeCalendar(fixture) if connected else None
    token = ("fake", "eval@example.com") if connected else None
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch(f"{_TOOL}._is_google_calendar_configured", lambda: True))
        stack.enter_context(patch(f"{_TOOL}._get_google_calendar_access_token", lambda: token))
        if fake is not None:
            stack.enter_context(patch(f"{_TOOL}._google_calendar_api_request", fake.api_request))
        yield fake
