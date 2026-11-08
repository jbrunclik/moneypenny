"""Agent timestamps: API responses carry explicit UTC offsets, and cooldown
ignores completion times in the future."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class TestAgentTimestampSerialization:
    """Agent-subsystem API responses must carry explicit UTC offsets."""

    def test_agent_response_timestamps_are_utc_aware(self) -> None:
        from src.api.helpers.agent_responses import agent_to_response
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
            created_at=datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC),
            updated_at=datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC),
            last_run_at=datetime(2026, 6, 10, 11, 0, 0, tzinfo=UTC),
            next_run_at=datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC),
        )
        data = agent_to_response(agent, daily_spending=0.0)
        assert data["created_at"] == "2026-06-10T12:00:00.000000+00:00"
        for field in ("created_at", "updated_at", "last_run_at", "next_run_at"):
            assert data[field].endswith("+00:00"), field
