"""Pure helpers behind the admin overview."""

from src.api.helpers.admin_overview import percentile


def test_percentile_picks_the_nearest_rank() -> None:
    assert percentile([], 0.5) is None
    assert percentile([1000, 3000], 0.5) == 1000  # the lower middle, not the max
    values = list(range(1, 21))  # 1..20
    assert percentile(values, 0.95) == 19  # not the maximum
    assert percentile(values, 1.0) == 20


def test_last_backup_counts_compressed_backups(tmp_path) -> None:
    from src.api.helpers.admin_overview import last_backup_at

    database = tmp_path / "chatbot.db"
    backups = tmp_path / "backups" / "chatbot.db"
    backups.mkdir(parents=True)
    assert last_backup_at(database) is None
    (backups / "chatbot-20261110-020000.db.zst").write_bytes(b"x")

    assert last_backup_at(database) is not None
