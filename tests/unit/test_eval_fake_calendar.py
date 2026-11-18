"""The eval harness's Google Calendar fake (evals/fake_calendar.py).

It replaces the tool's HTTP seam, so these tests drive the REAL
google_calendar tool through it.
"""

import json
from datetime import timedelta
from typing import Any

from evals.fakes import fake_integrations
from src.utils.clock import local_today


def _calendar() -> dict[str, Any]:
    today = local_today()
    tomorrow = (today + timedelta(days=1)).isoformat()
    in_20 = (today + timedelta(days=20)).isoformat()
    return {
        "state": "connected",
        "calendars": [{"id": "rodina@example.com", "summary": "Rodina", "primary": True}],
        "events": [
            {
                "id": "e1",
                "summary": "Kroužek keramiky",
                "start": {"dateTime": f"{tomorrow}T16:00:00+01:00"},
                "end": {"dateTime": f"{tomorrow}T17:30:00+01:00"},
            },
            {
                "id": "e2",
                "summary": "Zubař",
                "start": {"dateTime": f"{in_20}T09:00:00+01:00"},
                "end": {"dateTime": f"{in_20}T09:30:00+01:00"},
            },
            {
                "id": "e3",
                "summary": "Výlet na chatu",
                "start": {"date": tomorrow},
                "end": {"date": (today + timedelta(days=3)).isoformat()},
            },
        ],
    }


def _call(**args: Any) -> dict[str, Any]:
    from src.agent.tools.google_calendar import google_calendar

    out: dict[str, Any] = json.loads(google_calendar.invoke(args))
    return out


def test_list_events_returns_only_the_range(test_user: Any) -> None:
    from src.agent.tools.context import set_conversation_context

    set_conversation_context("c", test_user.id)
    try:
        with fake_integrations({"calendar": _calendar()}):
            out = _call(action="list_events")  # the tool's default: the next 7 days
    finally:
        set_conversation_context(None, None)
    assert sorted(e["summary"] for e in out["events"]) == ["Kroužek keramiky", "Výlet na chatu"]


def test_created_event_is_recorded_and_listed(test_user: Any) -> None:
    from src.agent.tools.context import set_conversation_context

    day = (local_today() + timedelta(days=2)).isoformat()
    set_conversation_context("c", test_user.id)
    try:
        with fake_integrations({"calendar": _calendar()}) as fakes:
            _call(
                action="create_event",
                summary="Vyzvednout Aničku",
                start_time=f"{day}T15:00:00+01:00",
                end_time=f"{day}T15:30:00+01:00",
            )
            listed = _call(action="list_events")
    finally:
        set_conversation_context(None, None)
    assert "Vyzvednout Aničku" in [e["summary"] for e in listed["events"]]
    [action] = fakes["calendar"].actions
    assert action.startswith("created event 'Vyzvednout Aničku'")


def test_update_and_delete_are_recorded(test_user: Any) -> None:
    from src.agent.tools.context import set_conversation_context

    set_conversation_context("c", test_user.id)
    try:
        with fake_integrations({"calendar": _calendar()}) as fakes:
            _call(action="update_event", event_id="e1", location="ZUŠ Lesná")
            _call(action="delete_event", event_id="e2")
    finally:
        set_conversation_context(None, None)
    assert fakes["calendar"].actions[0].startswith("updated event 'Kroužek keramiky'")
    assert "ZUŠ Lesná" in fakes["calendar"].actions[0]
    assert fakes["calendar"].actions[1] == "deleted event 'Zubař'"


def test_not_connected_is_the_real_message(test_user: Any) -> None:
    from src.agent.tools.context import set_conversation_context

    set_conversation_context("c", test_user.id)
    try:
        with fake_integrations({"calendar": {"state": "not_connected"}}):
            out = _call(action="list_events")
    finally:
        set_conversation_context(None, None)
    assert "connect" in json.dumps(out, ensure_ascii=False).lower()
