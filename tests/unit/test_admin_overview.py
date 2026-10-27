"""Pure helpers behind the admin overview."""

from src.api.helpers.admin_overview import percentile


def test_percentile_picks_the_nearest_rank() -> None:
    assert percentile([], 0.5) is None
    assert percentile([1000, 3000], 0.5) == 1000  # the lower middle, not the max
    values = list(range(1, 21))  # 1..20
    assert percentile(values, 0.95) == 19  # not the maximum
    assert percentile(values, 1.0) == 20
