"""Schedules are built by code from the model's structured fields, in the
household timezone - the model never writes a cron string or a UTC time."""

from datetime import UTC, datetime

import pytest

from src.utils.schedule_spec import (
    ScheduleError,
    describe_cron,
    describe_instant,
    describe_interval,
    next_cron_run,
    one_off_instant,
    recurring_cron,
    until_instant,
    watch_interval_hours,
)

_TZ = "Europe/Prague"
_NOW = datetime(2026, 11, 7, 18, 0, tzinfo=UTC)  # 19:00 in Prague


def test_one_off_is_a_utc_instant_in_the_household_timezone() -> None:
    assert one_off_instant("2026-11-13", "08:00", _TZ, _NOW) == datetime(
        2026, 11, 13, 7, 0, tzinfo=UTC
    )


def test_one_off_across_dst_uses_the_local_offset() -> None:
    assert one_off_instant("2027-03-29", "09:00", _TZ, _NOW) == datetime(
        2027, 3, 29, 7, 0, tzinfo=UTC
    )


def test_a_time_already_past_is_refused_naming_the_local_time() -> None:
    result = one_off_instant("2026-11-07", "08:00", _TZ, _NOW)

    assert isinstance(result, ScheduleError)
    assert "19:00" in result.message


@pytest.mark.parametrize(
    ("date", "time"), [("2026-13-01", "08:00"), ("2026-11-13", "25:00"), ("next friday", "8")]
)
def test_malformed_one_off_is_refused(date: str, time: str) -> None:
    assert isinstance(one_off_instant(date, time, _TZ, _NOW), ScheduleError)


@pytest.mark.parametrize(
    ("days", "time", "cron"),
    [
        (["mon"], "09:00", "0 9 * * 1"),
        (["mon", "thu"], "18:15", "15 18 * * 1,4"),
        (["weekdays"], "07:30", "30 7 * * 1-5"),
        (["weekends"], "10:00", "0 10 * * 0,6"),
        (["daily"], "08:00", "0 8 * * *"),
        (["Sun"], "20:00", "0 20 * * 0"),
    ],
)
def test_recurring_cron(days: list[str], time: str, cron: str) -> None:
    assert recurring_cron(days, time) == cron


@pytest.mark.parametrize(("days", "time"), [(["funday"], "09:00"), (["mon"], "9"), ([], "09:00")])
def test_malformed_recurring_is_refused(days: list[str], time: str) -> None:
    assert isinstance(recurring_cron(days, time), ScheduleError)


def test_descriptions_for_previews() -> None:
    assert (
        describe_instant(datetime(2026, 11, 13, 7, 0, tzinfo=UTC), _TZ) == "Fri 13 Nov 2026 08:00"
    )
    assert describe_cron("0 9 * * 1") == "every Monday at 09:00"
    assert describe_cron("30 7 * * 1-5") == "every weekday at 07:30"
    assert describe_cron("0 8 * * *") == "every day at 08:00"


@pytest.mark.parametrize(
    ("hint", "hours"), [("6h", 6), ("daily", 24), ("weekly", 168), (" Daily ", 24)]
)
def test_watch_interval_hours(hint: str, hours: int) -> None:
    assert watch_interval_hours(hint) == hours


@pytest.mark.parametrize("hint", ["1h", "hourly", "", "monthly"])
def test_watch_interval_hours_refuses_others(hint: str) -> None:
    result = watch_interval_hours(hint)
    assert isinstance(result, ScheduleError)
    assert "6h" in result.message and "daily" in result.message and "weekly" in result.message


def test_until_instant_is_the_end_of_that_local_day() -> None:
    assert until_instant("2026-12-24", _TZ, _NOW) == datetime(2026, 12, 24, 22, 59, 59, tzinfo=UTC)


@pytest.mark.parametrize("day", ["2026-11-06", "24.12.", "2026-02-30"])
def test_until_instant_refuses_past_or_malformed(day: str) -> None:
    assert isinstance(until_instant(day, _TZ, _NOW), ScheduleError)


@pytest.mark.parametrize(
    ("hours", "text"), [(6, "every 6 hours"), (24, "daily"), (168, "weekly"), (48, "every 2 days")]
)
def test_describe_interval(hours: int, text: str) -> None:
    assert describe_interval(hours) == text


def test_next_cron_run_is_local_time() -> None:
    # Sat 7 Nov 19:00 Prague -> Mon 9 Nov 09:00 Prague = 08:00 UTC
    assert next_cron_run("0 9 * * 1", _TZ, _NOW) == datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
