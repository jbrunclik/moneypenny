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
