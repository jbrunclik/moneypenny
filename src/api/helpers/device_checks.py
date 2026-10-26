"""Device check runner: the fixture conversation's script and run tallies."""

from typing import TypedDict

from src.api.schemas.device_checks import DeviceCheckRunRequest, DeviceCheckStatus
from src.db.models import db
from src.db.models.device_checks import DeviceCheckRunRow, DeviceCheckScenarioRow

FIXTURE_TITLE = "Device check (temporary)"
FIXTURE_TURNS = 40

# Varied lengths and shapes, like a real chat: short answers, paragraphs,
# a list, a code block - the scroll checks need a list taller than any screen
_ANSWERS = (
    "Sure - here is the short version.",
    "This one takes a few paragraphs.\n\n"
    + "Layout checks need content that is taller than the screen. " * 6
    + "\n\nA second paragraph keeps the reply long enough to scroll through.",
    "Three things to check:\n\n1. The list ends at the bottom.\n"
    "2. The composer sits on the keyboard.\n3. Nothing pans the window.",
    "A code block:\n\n```python\ndef settle(inset: int) -> bool:\n    return inset == 0\n```",
)


class FixtureInfo(TypedDict):
    conversation_id: str
    message_count: int


def fixture_messages() -> list[tuple[str, str]]:
    """The scripted turns: (role, content), oldest first."""
    messages: list[tuple[str, str]] = []
    for turn in range(1, FIXTURE_TURNS + 1):
        messages.append(("user", f"Fixture question {turn}"))
        messages.append(("assistant", _ANSWERS[turn % len(_ANSWERS)]))
    return messages


def create_fixture(user_id: str) -> FixtureInfo:
    """Purge any fixture a crashed run left, then write a fresh one."""
    db.purge_device_check_fixtures(user_id)
    messages = fixture_messages()
    conversation_id = db.create_device_check_fixture(user_id, FIXTURE_TITLE, messages)
    return {"conversation_id": conversation_id, "message_count": len(messages)}


def save_run(user_id: str, data: DeviceCheckRunRequest) -> DeviceCheckRunRow:
    """Store a run with its passed / failed (errors included) / skipped tallies."""
    statuses = [scenario.status for scenario in data.scenarios]
    failed = sum(s in {DeviceCheckStatus.FAILED, DeviceCheckStatus.ERROR} for s in statuses)
    counts = (
        statuses.count(DeviceCheckStatus.PASSED),
        failed,
        statuses.count(DeviceCheckStatus.SKIPPED),
    )
    scenarios: list[DeviceCheckScenarioRow] = [
        {
            "id": s.id,
            "title": s.title,
            "status": s.status.value,
            "duration_ms": s.duration_ms,
            "measurements": dict(s.measurements),
            "notes": list(s.notes),
        }
        for s in data.scenarios
    ]
    return db.add_device_check_run(
        user_id,
        {
            "build_marker": data.build_marker,
            "app_version": data.app_version,
            "standalone": data.standalone,
            "ua_summary": data.ua_summary,
            "environment": dict(data.environment),
            "scenarios": scenarios,
            "started_at": data.started_at,
            "finished_at": data.finished_at,
        },
        counts,
    )
