"""Pure helpers behind the admin overview."""

from datetime import UTC, datetime

from src.api.helpers.admin_overview import local_time, percentile


def test_percentile_picks_the_nearest_rank() -> None:
    assert percentile([], 0.5) is None
    assert percentile([1000, 3000], 0.5) == 1000  # the lower middle, not the max
    values = list(range(1, 21))  # 1..20
    assert percentile(values, 0.95) == 19  # not the maximum
    assert percentile(values, 1.0) == 20


def test_local_time_converts_stored_utc() -> None:
    stored = datetime(2026, 10, 25, 6, 0)  # UTC-naive, as agent runs store it
    expected = stored.replace(tzinfo=UTC).astimezone().replace(tzinfo=None)
    assert local_time(stored.isoformat()) == expected.isoformat(timespec="seconds")
    assert local_time(None) is None
