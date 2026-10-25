"""Admin page queries (src/db/models/admin.py) against a real test database."""

from datetime import datetime
from typing import Any

import pytest

from src.db.models import Database, User

NOW = datetime(2026, 10, 25, 15, 0)
TODAY = datetime(2026, 10, 25)
MONTH = datetime(2026, 10, 1)


def _cost(db: Database, user: User, usd: float, at: datetime, **kwargs: Any) -> str:
    conversation = kwargs.pop("conversation", None) or db.create_conversation(user.id, "Chat")
    message = db.add_message(conversation.id, "assistant", "answer")
    db.save_message_cost(
        message_id=message.id,
        conversation_id=conversation.id,
        user_id=user.id,
        model=kwargs.pop("model", "gemini-3.8-flash"),
        input_tokens=10,
        output_tokens=10,
        cost_usd=usd,
        **kwargs,
    )
    with db._pool.get_connection() as conn:
        conn.execute(
            "UPDATE message_costs SET created_at = ? WHERE message_id = ?",
            (at.isoformat(), message.id),
        )
        conn.commit()
    return conversation.id


@pytest.fixture
def other_user(test_database: Database) -> User:
    return test_database.get_or_create_user(email="other@example.com", name="Other")


class TestSpend:
    def test_per_user_today_and_month(
        self, test_database: Database, test_user: User, other_user: User
    ) -> None:
        _cost(test_database, test_user, 2.0, NOW)
        _cost(test_database, test_user, 3.0, datetime(2026, 10, 3, 9, 0))
        _cost(test_database, test_user, 50.0, datetime(2026, 9, 30, 9, 0))  # last month
        rows = {r["user_id"]: r for r in test_database.admin_spend_per_user(TODAY, MONTH)}
        assert rows[test_user.id]["today_usd"] == pytest.approx(2.0)
        assert rows[test_user.id]["month_usd"] == pytest.approx(5.0)
        # Users without spend are listed too
        assert rows[other_user.id]["today_usd"] == 0
        assert rows[other_user.id]["name"] == "Other"

    def test_user_spend_since(self, test_database: Database, test_user: User) -> None:
        _cost(test_database, test_user, 4.0, NOW)
        _cost(test_database, test_user, 7.0, datetime(2026, 10, 24, 23, 0))
        assert test_database.user_spend_since(test_user.id, TODAY) == pytest.approx(4.0)

    def test_by_day_fills_only_days_with_spend(
        self, test_database: Database, test_user: User
    ) -> None:
        _cost(test_database, test_user, 1.0, datetime(2026, 10, 24, 10, 0))
        _cost(test_database, test_user, 2.0, datetime(2026, 10, 24, 20, 0))
        _cost(test_database, test_user, 3.0, NOW)
        days = dict(test_database.admin_spend_by_day(datetime(2026, 10, 20)))
        assert days == {"2026-10-24": pytest.approx(3.0), "2026-10-25": pytest.approx(3.0)}

    def test_by_feature_and_model(self, test_database: Database, test_user: User) -> None:
        planner = test_database.get_or_create_planner_conversation(test_user.id)
        _cost(test_database, test_user, 1.0, NOW)
        _cost(test_database, test_user, 2.0, NOW, conversation=planner, model="gemini-pro")
        features = test_database.admin_spend_by_feature(MONTH)
        assert features["chat"] == pytest.approx(1.0)
        assert features["planner"] == pytest.approx(2.0)
        models = test_database.admin_spend_by_model(MONTH)
        assert models == {"gemini-3.8-flash": pytest.approx(1.0), "gemini-pro": pytest.approx(2.0)}

    def test_spend_from_deleted_conversations_still_counts(
        self, test_database: Database, test_user: User
    ) -> None:
        conversation_id = _cost(test_database, test_user, 5.0, NOW)
        with test_database._pool.get_connection() as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            conn.commit()
        assert test_database.admin_spend_by_feature(MONTH)["deleted"] == pytest.approx(5.0)


class TestTurnsAndAgents:
    def test_turn_stats(self, test_database: Database, test_user: User) -> None:
        _cost(test_database, test_user, 0.1, NOW, duration_ms=1000)
        _cost(test_database, test_user, 0.1, NOW, duration_ms=3000, tool_errors=2)
        _cost(test_database, test_user, 0.1, datetime(2026, 9, 1), duration_ms=99999)
        stats = test_database.admin_turn_stats(datetime(2026, 10, 18))
        assert stats["turns"] == 2
        assert sorted(stats["durations_ms"]) == [1000, 3000]
        assert stats["turns_with_tool_errors"] == 1

    def test_agent_runs_and_failures(self, test_database: Database, test_user: User) -> None:
        agent = test_database.create_agent(test_user.id, "Briefing")
        ok = test_database.create_execution(agent.id, "scheduled")
        test_database.update_execution(ok.id, status="completed")
        bad = test_database.create_execution(agent.id, "scheduled")
        test_database.update_execution(
            bad.id, status="failed", error_message="x" * 500 + "\nquoted page text"
        )
        stats = test_database.admin_agent_runs(datetime(2000, 1, 1))
        assert (stats["runs"], stats["failed"]) == (2, 1)
        failure = test_database.admin_recent_agent_failures(limit=5)[0]
        assert failure["agent_name"] == "Briefing"
        assert failure["user_name"] == test_user.name
        # First line only, short: an error can quote someone's content
        assert len(failure["error"]) <= 120
        assert "quoted page text" not in failure["error"]

    def test_system_facts(self, test_database: Database, test_user: User) -> None:
        assert test_database.admin_user_count() >= 1
        assert (test_database.admin_latest_migration() or "").startswith("00")
