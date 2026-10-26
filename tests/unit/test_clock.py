"""src/utils/clock.py: aware UTC now and APP_TIMEZONE day boundaries.

The DST tables use Europe/Prague's 2026 transitions: spring forward on Mar 29
(02:00 CET -> 03:00 CEST, at 01:00Z) and fall back on Oct 25 (03:00 CEST ->
02:00 CET, at 01:00Z). Expected values are written as UTC instants.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.config import Config
from src.utils import clock
from src.utils.clock import (
    app_tz,
    local_day_start,
    local_month_bounds,
    local_today,
    planner_cutoff,
    to_api,
    utc_now,
)

PRAGUE = ZoneInfo("Europe/Prague")


def _z(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _local(year: int, month: int, day: int, hour: int, minute: int = 0, fold: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=PRAGUE, fold=fold)


@pytest.fixture(autouse=True)
def _prague(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "APP_TIMEZONE", "Europe/Prague")


class TestNow:
    def test_utc_now_is_aware_utc(self) -> None:
        now = utc_now()
        assert now.tzinfo is UTC
        assert abs(now - datetime.now(UTC)) < timedelta(seconds=2)

    def test_utc_now_reads_the_seam(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fixed = _z(2026, 10, 25, 1, 30)
        monkeypatch.setattr(clock, "_now", lambda: fixed)
        assert utc_now() == fixed

    def test_app_tz_follows_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert app_tz() == PRAGUE
        monkeypatch.setattr(Config, "APP_TIMEZONE", "Pacific/Chatham")
        assert app_tz() == ZoneInfo("Pacific/Chatham")


class TestLocalToday:
    @pytest.mark.parametrize(
        ("now", "expected"),
        [
            (_z(2026, 10, 25, 22, 59), date(2026, 10, 25)),  # 23:59 CET
            (_z(2026, 10, 25, 23, 0), date(2026, 10, 26)),  # 00:00 CET
            (_z(2026, 7, 15, 21, 59), date(2026, 7, 15)),  # 23:59 CEST
            (_z(2026, 7, 15, 22, 0), date(2026, 7, 16)),  # 00:00 CEST
            (_z(2026, 3, 28, 23, 0), date(2026, 3, 29)),  # 00:00 CET, spring-forward day
        ],
    )
    def test_local_date_at(self, now: datetime, expected: date) -> None:
        assert local_today(now) == expected

    def test_defaults_to_the_seam(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(clock, "_now", lambda: _z(2026, 12, 31, 23, 30))
        assert local_today() == date(2027, 1, 1)

    def test_rejects_naive(self) -> None:
        with pytest.raises(ValueError, match="naive"):
            local_today(datetime(2026, 1, 1))


class TestLocalDayStart:
    @pytest.mark.parametrize(
        ("dt", "expected"),
        [
            # Normal winter and summer days
            (_z(2026, 1, 15, 12), _z(2026, 1, 14, 23)),
            (_z(2026, 7, 15, 12), _z(2026, 7, 14, 22)),
            # Spring-forward day (23 h): starts in CET
            (_z(2026, 3, 28, 23, 0), _z(2026, 3, 28, 23)),  # its first instant
            (_z(2026, 3, 29, 0, 59), _z(2026, 3, 28, 23)),  # 01:59 CET, just before
            (_z(2026, 3, 29, 1, 0), _z(2026, 3, 28, 23)),  # 03:00 CEST, just after
            (_z(2026, 3, 29, 21, 59), _z(2026, 3, 28, 23)),  # 23:59 CEST, its last minute
            (_z(2026, 3, 28, 22, 59), _z(2026, 3, 27, 23)),  # 23:59 CET the day before
            # The day after starts in CEST
            (_z(2026, 3, 29, 22, 0), _z(2026, 3, 29, 22)),
            # Fall-back day (25 h): starts in CEST
            (_z(2026, 10, 24, 22, 0), _z(2026, 10, 24, 22)),
            (_z(2026, 10, 25, 0, 30), _z(2026, 10, 24, 22)),  # 02:30 CEST (first)
            (_z(2026, 10, 25, 1, 30), _z(2026, 10, 24, 22)),  # 02:30 CET (repeat)
            (_z(2026, 10, 25, 22, 59), _z(2026, 10, 24, 22)),  # 23:59 CET, its last minute
            # The day after starts in CET
            (_z(2026, 10, 25, 23, 0), _z(2026, 10, 25, 23)),
        ],
    )
    def test_start_of_local_day(self, dt: datetime, expected: datetime) -> None:
        start = local_day_start(dt)
        assert start == expected
        assert start.tzinfo is UTC

    def test_day_lengths_across_transitions(self) -> None:
        def length(day_noon: datetime) -> timedelta:
            return local_day_start(day_noon + timedelta(days=1)) - local_day_start(day_noon)

        assert length(_z(2026, 3, 29, 10)) == timedelta(hours=23)
        assert length(_z(2026, 10, 25, 10)) == timedelta(hours=25)
        assert length(_z(2026, 6, 1, 10)) == timedelta(hours=24)

    def test_accepts_any_aware_zone(self) -> None:
        assert local_day_start(_local(2026, 10, 25, 2, 30, fold=1)) == _z(2026, 10, 24, 22)

    def test_skipped_midnight_starts_at_the_transition(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """America/Havana springs forward at midnight (00:00 -05:00 -> 01:00
        -04:00), so its Mar 8 has no 00:00: the day starts at the transition
        instant, 05:00Z (midnight read with the pre-gap offset)."""
        monkeypatch.setattr(Config, "APP_TIMEZONE", "America/Havana")
        assert local_day_start(_z(2026, 3, 8, 12)) == _z(2026, 3, 8, 5)

    def test_rejects_naive(self) -> None:
        with pytest.raises(ValueError, match="naive"):
            local_day_start(datetime(2026, 1, 1, 12))


class TestLocalMonthBounds:
    @pytest.mark.parametrize(
        ("year", "month", "start", "end"),
        [
            (2026, 1, _z(2025, 12, 31, 23), _z(2026, 1, 31, 23)),
            # March holds the spring-forward: starts in CET, ends in CEST
            (2026, 3, _z(2026, 2, 28, 23), _z(2026, 3, 31, 22)),
            (2026, 7, _z(2026, 6, 30, 22), _z(2026, 7, 31, 22)),
            # October holds the fall-back: starts in CEST, ends in CET
            (2026, 10, _z(2026, 9, 30, 22), _z(2026, 10, 31, 23)),
            # December rolls the year
            (2026, 12, _z(2026, 11, 30, 23), _z(2026, 12, 31, 23)),
        ],
    )
    def test_bounds(self, year: int, month: int, start: datetime, end: datetime) -> None:
        assert local_month_bounds(year, month) == (start, end)

    def test_bounds_are_aware_utc_and_tile(self) -> None:
        months = [local_month_bounds(2026, m) for m in range(1, 13)]
        assert all(s.tzinfo is UTC and e.tzinfo is UTC for s, e in months)
        assert all(months[i][1] == months[i + 1][0] for i in range(11))
        assert months[2][1] - months[2][0] == timedelta(days=31, hours=-1)
        assert months[9][1] - months[9][0] == timedelta(days=31, hours=1)


class TestPlannerCutoff:
    @pytest.mark.parametrize(
        ("now", "expected"),
        [
            # Normal winter day: 04:00 CET = 03:00Z
            (_local(2026, 1, 15, 3, 59), _z(2026, 1, 14, 3)),
            (_local(2026, 1, 15, 4, 0), _z(2026, 1, 15, 3)),
            (_local(2026, 1, 15, 4, 1), _z(2026, 1, 15, 3)),
            # Normal summer day: 04:00 CEST = 02:00Z
            (_local(2026, 7, 15, 3, 59), _z(2026, 7, 14, 2)),
            (_local(2026, 7, 15, 4, 0), _z(2026, 7, 15, 2)),
            (_local(2026, 7, 15, 4, 1), _z(2026, 7, 15, 2)),
            # Spring-forward day: yesterday's 4am was CET, today's is CEST
            (_local(2026, 3, 29, 3, 59), _z(2026, 3, 28, 3)),
            (_local(2026, 3, 29, 4, 0), _z(2026, 3, 29, 2)),
            (_local(2026, 3, 29, 4, 1), _z(2026, 3, 29, 2)),
            (_local(2026, 3, 29, 1, 30), _z(2026, 3, 28, 3)),  # before the jump
            # The day after
            (_local(2026, 3, 30, 3, 59), _z(2026, 3, 29, 2)),
            (_local(2026, 3, 30, 4, 0), _z(2026, 3, 30, 2)),
            # Fall-back day: yesterday's 4am was CEST, today's is CET
            (_local(2026, 10, 25, 3, 59), _z(2026, 10, 24, 2)),
            (_local(2026, 10, 25, 4, 0), _z(2026, 10, 25, 3)),
            (_local(2026, 10, 25, 4, 1), _z(2026, 10, 25, 3)),
            (_local(2026, 10, 25, 2, 30, fold=0), _z(2026, 10, 24, 2)),  # first 02:30
            (_local(2026, 10, 25, 2, 30, fold=1), _z(2026, 10, 24, 2)),  # repeated 02:30
            # The day after
            (_local(2026, 10, 26, 3, 59), _z(2026, 10, 25, 3)),
            (_local(2026, 10, 26, 4, 0), _z(2026, 10, 26, 3)),
            # Year boundary
            (_local(2027, 1, 1, 0, 30), _z(2026, 12, 31, 3)),
        ],
    )
    def test_most_recent_local_4am(self, now: datetime, expected: datetime) -> None:
        cutoff = planner_cutoff(now)
        assert cutoff == expected
        assert cutoff.tzinfo is UTC
        assert cutoff <= now

    def test_same_instant_in_utc(self) -> None:
        now = _local(2026, 10, 25, 4, 0)
        assert planner_cutoff(now.astimezone(UTC)) == planner_cutoff(now)

    def test_planner_days_span_23_and_25_hours(self) -> None:
        def day_length(local_day: date) -> timedelta:
            def at(d: date) -> datetime:
                return planner_cutoff(datetime(d.year, d.month, d.day, 12, tzinfo=PRAGUE))

            return at(local_day + timedelta(days=1)) - at(local_day)

        assert day_length(date(2026, 3, 28)) == timedelta(hours=23)
        assert day_length(date(2026, 10, 24)) == timedelta(hours=25)
        assert day_length(date(2026, 5, 5)) == timedelta(hours=24)

    def test_rejects_naive(self) -> None:
        with pytest.raises(ValueError, match="naive"):
            planner_cutoff(datetime(2026, 1, 15, 5))


class TestToApi:
    @pytest.mark.parametrize(
        ("dt", "expected"),
        [
            (_z(2026, 10, 25, 1, 0), "2026-10-25T01:00:00.000000+00:00"),
            (
                datetime(2026, 10, 25, 1, 0, 0, 7, tzinfo=UTC),
                "2026-10-25T01:00:00.000007+00:00",
            ),
            (_local(2026, 7, 15, 10, 0), "2026-07-15T08:00:00.000000+00:00"),
            (_local(2026, 10, 25, 2, 30, fold=1), "2026-10-25T01:30:00.000000+00:00"),
        ],
    )
    def test_fixed_width_utc(self, dt: datetime, expected: str) -> None:
        assert to_api(dt) == expected
        assert len(to_api(dt)) == len("YYYY-MM-DDTHH:MM:SS.ffffff+00:00")

    def test_round_trips(self) -> None:
        dt = datetime(2026, 3, 29, 1, 0, 0, 123456, tzinfo=UTC)
        assert datetime.fromisoformat(to_api(dt)) == dt

    def test_strings_sort_chronologically(self) -> None:
        base = _z(2026, 10, 25, 0, 59)
        instants = [base + timedelta(microseconds=n * 250_000) for n in range(12)]
        assert sorted(instants, key=to_api) == instants
        assert sorted(map(to_api, instants)) == [to_api(i) for i in instants]

    def test_rejects_naive(self) -> None:
        with pytest.raises(ValueError, match="naive"):
            to_api(datetime(2026, 1, 1))
