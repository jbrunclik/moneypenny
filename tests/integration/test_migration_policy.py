"""Only the web app applies migrations; timers and scripts skip a run instead.

`make update` pulls the new code before the new workers start, and the
per-minute agent-scheduler timer used to construct Database with that code and
apply the new migration on its own - before the deploy's backup existed and
outside the health gate.
"""

import importlib.util
import shutil
import sqlite3
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.db.models import Database, use_database
from src.db.models import base as db_base

REPO_ROOT = Path(__file__).parent.parent.parent

_PROBE_MIGRATION = """
from yoyo import step

__depends__ = {"%s"}

steps = [step("CREATE TABLE probe_pending (id INTEGER)", "DROP TABLE probe_pending")]
"""


@pytest.fixture
def pending_db(test_db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A database migrated to main, with one more migration waiting."""
    Database(db_path=test_db_path).close()
    migrations = tmp_path / "migrations"
    shutil.copytree(db_base.MIGRATIONS_DIR, migrations)
    latest = sorted(p.stem for p in migrations.glob("[0-9]*.py"))[-1]
    (migrations / "9999_probe_pending.py").write_text(_PROBE_MIGRATION % latest)
    monkeypatch.setattr(db_base, "MIGRATIONS_DIR", migrations)
    return test_db_path


def _tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    finally:
        conn.close()


def test_without_apply_a_pending_migration_is_left_alone(pending_db: Path) -> None:
    db = Database(db_path=pending_db, apply_migrations=False)

    assert db.pending_migration_count() == 1
    assert "probe_pending" not in _tables(pending_db)
    db.close()


def test_default_construction_still_applies(pending_db: Path) -> None:
    db = Database(db_path=pending_db)

    assert db.pending_migration_count() == 0
    assert "probe_pending" in _tables(pending_db)
    db.close()


def test_global_database_does_not_migrate_on_import() -> None:
    import src.db.models as models

    source = Path(models.__file__).read_text()
    assert "_DatabaseHandle(Database(apply_migrations=False))" in source


def _load_scheduler_script() -> ModuleType:
    path = REPO_ROOT / "scripts" / "run_agent_scheduler.py"
    spec = importlib.util.spec_from_file_location("run_agent_scheduler_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scheduler_timer_skips_its_run_while_migrations_are_pending(pending_db: Path) -> None:
    timer_db = Database(db_path=pending_db, apply_migrations=False)
    with (
        use_database(timer_db),
        patch("src.agent.scheduler.run_scheduled_agents") as run,
        patch("src.db.models.logger") as logger,
    ):
        _load_scheduler_script().main()

    run.assert_not_called()
    assert "probe_pending" not in _tables(pending_db)
    logger.info.assert_called_once_with(
        "Migrations pending, skipping", extra={"job": "agent-scheduler", "pending": 1}
    )
    timer_db.close()


def test_scheduler_timer_runs_when_nothing_is_pending(test_database: Database) -> None:
    with (
        use_database(test_database),
        patch("src.agent.scheduler.run_scheduled_agents") as run,
    ):
        _load_scheduler_script().main()

    run.assert_called_once()


def test_web_app_applies_pending_migrations(pending_db: Path) -> None:
    web_db = Database(db_path=pending_db, apply_migrations=False)
    with use_database(web_db):
        from src.app import create_app

        create_app()

    assert "probe_pending" in _tables(pending_db)
    web_db.close()


def test_migration_lock_timeout_comes_from_config(
    test_db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Config, "MIGRATION_LOCK_TIMEOUT_SECONDS", 7)
    backend = MagicMock()
    backend.to_apply.return_value = ["pending"]
    with patch.object(db_base, "get_backend", return_value=backend):
        Database(db_path=test_db_path)

    backend.lock.assert_called_once_with(timeout=7)


def test_migration_lock_timeout_default_outlasts_a_long_migration() -> None:
    assert Config.MIGRATION_LOCK_TIMEOUT_SECONDS >= 300
