"""Daily Briefing: its delivery time as a daily cron, and the fresh-context rule."""

import pytest

from src.utils.cron import daily_cron, daily_cron_time


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
        assert daily_cron(time_str) == cron

    @pytest.mark.parametrize("bad", ["24:00", "8:00", "08:60", "abc", "", "08:00:00"])
    def test_invalid_raises(self, bad: str) -> None:
        with pytest.raises(ValueError, match="Invalid time"):
            daily_cron(bad)


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
        assert daily_cron_time(cron) == time_str

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
        assert daily_cron_time(cron) is None

    def test_round_trip(self) -> None:
        assert daily_cron_time(daily_cron("06:45")) == "06:45"


class TestFreshContext:
    """fresh_context column round-trips and briefing agents enforce it."""

    def test_create_and_update_round_trip(self, test_database, test_user) -> None:
        agent = test_database.create_standing_chat(
            user_id=test_user.id, name="A1", fresh_context=False
        )
        assert test_database.get_standing_chat(agent.id, test_user.id).fresh_context is False

        test_database.update_standing_chat(agent.id, test_user.id, fresh_context=True)
        assert test_database.get_standing_chat(agent.id, test_user.id).fresh_context is True

    def test_create_defaults_to_fresh(self, test_database, test_user) -> None:
        agent = test_database.create_standing_chat(user_id=test_user.id, name="A2")
        assert agent.fresh_context is True

    def test_briefing_agent_is_fresh_context(self, test_database, test_user, monkeypatch) -> None:
        monkeypatch.setattr("src.agent.daily_briefing.db", test_database)
        from src.agent.daily_briefing import set_briefing

        set_briefing(test_user, enabled=True, time_str="07:00", timezone="Europe/Prague")
        user = test_database.get_user_by_id(test_user.id)
        agent = test_database.get_standing_chat(user.daily_briefing_job_id, user.id)
        assert agent.fresh_context is True


class TestAutonomousPromptContext:
    """The Conversation Context section must match how the executor
    actually builds history for the agent."""

    def test_fresh_context_variant(self) -> None:
        from src.agent.prompt_agents import get_autonomous_agent_prompt

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
        from src.agent.prompt_agents import get_autonomous_agent_prompt

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


def test_briefing_prompt_mentions_leave_by_routing() -> None:
    from src.agent.daily_briefing import BRIEFING_SYSTEM_PROMPT

    assert "get_route" in BRIEFING_SYSTEM_PROMPT
    assert "leave by" in BRIEFING_SYSTEM_PROMPT.lower()


class TestBriefingIsAStandingChat:
    """Standing chats phase 2 (B4): the Settings toggle makes a standing chat
    plus a daily standing job; turning it off pauses the job."""

    def _briefing(self, test_database, test_user, monkeypatch, enabled: bool = True):
        monkeypatch.setattr("src.agent.daily_briefing.db", test_database)
        from src.agent.daily_briefing import set_briefing

        current = test_database.get_user_by_id(test_user.id)  # with its briefing id
        set_briefing(current, enabled=enabled, time_str="07:15", timezone="Europe/Prague")
        user = test_database.get_user_by_id(test_user.id)
        return user.daily_briefing_job_id

    def test_settings_toggle_creates_chat_and_job(self, test_database, test_user, monkeypatch):
        from src.agent.daily_briefing import SYSTEM_TYPE_DAILY_BRIEFING

        job_id = self._briefing(test_database, test_user, monkeypatch)

        job = test_database.get_item(job_id, test_user.id)
        assert job is not None and job.standing
        assert (job.schedule, job.timezone, job.grants) == ("15 7 * * *", "Europe/Prague", ["*"])
        conv = test_database.get_conversation(job.conversation_id, test_user.id)
        assert conv.is_agent and conv.job_id == job_id
        assert (conv.standing_instructions, conv.standing_type) == (
            None,
            SYSTEM_TYPE_DAILY_BRIEFING,
        )

    def test_toggle_off_pauses_the_job(self, test_database, test_user, monkeypatch):
        job_id = self._briefing(test_database, test_user, monkeypatch)

        self._briefing(test_database, test_user, monkeypatch, enabled=False)

        job = test_database.get_item(job_id, test_user.id)
        assert (job.status, job.paused_reason) == ("paused", "disabled")


def test_create_agent_makes_chat_and_job(test_database, test_user) -> None:
    agent = test_database.create_standing_chat(
        test_user.id,
        "Coach",
        instructions="Coach my rides",
        schedule="0 20 * * *",
        grants=["garmin_connect"],
        budget_usd=0.3,
        fresh_context=False,
    )

    job = test_database.get_item(agent.id, test_user.id)
    conv = test_database.get_conversation(agent.conversation_id, test_user.id)
    assert (job.grants, job.budget_usd, job.fresh_context) == (["garmin_connect"], 0.3, False)
    assert (conv.standing_name, conv.standing_instructions) == ("Coach", "Coach my rides")
    assert test_database.count_items(test_user.id) == 0  # outside the light-item cap
