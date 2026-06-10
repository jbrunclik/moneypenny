"""Unit tests for datetime conventions (R9 timezone normalization)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.models import Database, User

from src.utils.datetime_utils import to_utc_iso, utcnow_naive


class TestUtcnowNaive:
    def test_is_naive(self) -> None:
        assert utcnow_naive().tzinfo is None

    def test_matches_aware_utc(self) -> None:
        delta = abs(utcnow_naive() - datetime.now(UTC).replace(tzinfo=None))
        assert delta < timedelta(seconds=2)


class TestToUtcIso:
    def test_appends_utc_offset(self) -> None:
        dt = datetime(2026, 6, 10, 12, 0, 0)
        assert to_utc_iso(dt) == "2026-06-10T12:00:00+00:00"

    def test_javascript_parseable_marker(self) -> None:
        """Naive ISO strings parse as browser-local in JS; the marker fixes it."""
        assert to_utc_iso(utcnow_naive()).endswith("+00:00")


class TestAgentTimestampSerialization:
    """Agent-subsystem API responses must carry explicit UTC offsets."""

    def test_agent_response_timestamps_are_utc_aware(self) -> None:
        from src.api.routes.agents import _agent_to_response
        from src.db.models.dataclasses import Agent

        agent = Agent(
            id="agent-1",
            user_id="user-1",
            conversation_id="conv-1",
            name="A",
            description=None,
            system_prompt=None,
            schedule=None,
            timezone="UTC",
            enabled=True,
            tool_permissions=None,
            model="gemini-3-flash-preview",
            created_at=datetime(2026, 6, 10, 12, 0, 0),
            updated_at=datetime(2026, 6, 10, 12, 0, 0),
            last_run_at=datetime(2026, 6, 10, 11, 0, 0),
            next_run_at=datetime(2026, 6, 11, 12, 0, 0),
        )
        data = _agent_to_response(agent, daily_spending=0.0)
        for field in ("created_at", "updated_at", "last_run_at", "next_run_at"):
            assert data[field].endswith("+00:00"), field


class TestCooldownFutureClamp:
    """is_in_cooldown must ignore bogus future completed_at timestamps.

    Guards the local-naive -> UTC-naive transition: rows written under the
    old convention on a UTC+N host appear up to N hours in the future and
    would otherwise pin the agent in cooldown.
    """

    def test_future_completed_at_not_in_cooldown(
        self, test_database: Database, test_user: User
    ) -> None:
        agent = test_database.create_agent(user_id=test_user.id, name="cooldown-clamp")
        execution = test_database.create_execution(agent.id, "manual")
        future = (utcnow_naive() + timedelta(hours=2)).isoformat()
        with test_database._pool.get_connection() as conn:
            conn.execute(
                "UPDATE agent_executions SET status='completed', completed_at=? WHERE id=?",
                (future, execution.id),
            )
            conn.commit()

        assert test_database.is_in_cooldown(agent.id) is False

    def test_recent_completed_at_in_cooldown(
        self, test_database: Database, test_user: User
    ) -> None:
        agent = test_database.create_agent(user_id=test_user.id, name="cooldown-recent")
        execution = test_database.create_execution(agent.id, "manual")
        test_database.update_execution(execution.id, status="completed")

        assert test_database.is_in_cooldown(agent.id) is True
