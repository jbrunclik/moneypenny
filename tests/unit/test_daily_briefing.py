"""Unit tests for the Daily Briefing time/cron helpers."""

import pytest

from src.agent.daily_briefing import _cron_to_time, _time_to_cron


class TestTimeToCron:
    @pytest.mark.parametrize(
        ("time_str", "cron"),
        [
            ("08:00", "0 8 * * *"),
            ("07:30", "30 7 * * *"),
            ("00:00", "0 0 * * *"),
            ("23:59", "59 23 * * *"),
        ],
    )
    def test_valid(self, time_str: str, cron: str) -> None:
        assert _time_to_cron(time_str) == cron

    @pytest.mark.parametrize("bad", ["24:00", "8:00", "08:60", "abc", "", "08:00:00"])
    def test_invalid_raises(self, bad: str) -> None:
        with pytest.raises(ValueError, match="Invalid briefing time"):
            _time_to_cron(bad)


class TestCronToTime:
    @pytest.mark.parametrize(
        ("cron", "time_str"),
        [
            ("0 8 * * *", "08:00"),
            ("30 7 * * *", "07:30"),
            ("59 23 * * *", "23:59"),
        ],
    )
    def test_valid(self, cron: str, time_str: str) -> None:
        assert _cron_to_time(cron) == time_str

    @pytest.mark.parametrize(
        "cron",
        [
            None,
            "",
            "0 8 * * 1",  # weekly, not daily
            "*/5 * * * *",  # not a fixed time
            "0 25 * * *",  # invalid hour
        ],
    )
    def test_non_daily_returns_none(self, cron: str | None) -> None:
        assert _cron_to_time(cron) is None

    def test_round_trip(self) -> None:
        assert _cron_to_time(_time_to_cron("06:45")) == "06:45"


class TestFreshContext:
    """fresh_context column round-trips and briefing agents enforce it."""

    def test_create_and_update_round_trip(self, test_database, test_user) -> None:
        agent = test_database.create_agent(user_id=test_user.id, name="A1", fresh_context=False)
        assert test_database.get_agent(agent.id, test_user.id).fresh_context is False

        test_database.update_agent(agent.id, test_user.id, fresh_context=True)
        assert test_database.get_agent(agent.id, test_user.id).fresh_context is True

    def test_create_defaults_to_fresh(self, test_database, test_user) -> None:
        agent = test_database.create_agent(user_id=test_user.id, name="A2")
        assert agent.fresh_context is True

    def test_briefing_agent_is_fresh_context(self, test_database, test_user, monkeypatch) -> None:
        monkeypatch.setattr("src.db.models.db", test_database)
        from src.agent.daily_briefing import set_briefing

        set_briefing(test_user, enabled=True, time_str="07:00", timezone="Europe/Prague")
        user = test_database.get_user_by_id(test_user.id)
        agent = test_database.get_agent(user.daily_briefing_agent_id, user.id)
        assert agent.fresh_context is True


class TestAutonomousPromptContext:
    """The Conversation Context section must match how the executor
    actually builds history for the agent."""

    def test_fresh_context_variant(self) -> None:
        from src.agent.prompts import get_autonomous_agent_prompt

        prompt = get_autonomous_agent_prompt(
            "Daily Briefing",
            None,
            "0 8 * * *",
            "UTC",
            "goals",
            [],
            "scheduled",
            fresh_context=True,
        )
        assert "clean slate" in prompt
        assert "persistent conversation" not in prompt

    def test_persistent_variant_is_default(self) -> None:
        from src.agent.prompts import get_autonomous_agent_prompt

        prompt = get_autonomous_agent_prompt(
            "Research",
            None,
            None,
            "UTC",
            "goals",
            [],
            "manual",
        )
        assert "persistent conversation" in prompt
        assert "clean slate" not in prompt
