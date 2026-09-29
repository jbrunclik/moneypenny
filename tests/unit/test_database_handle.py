"""The global ``db`` is a swappable handle, so one swap reaches every importer.

Test harnesses used to patch ``db`` per module; a module missing from the
list (the E2E server lacked ``routes.rouvy``) silently hit the wrong database.
"""

from __future__ import annotations

from pathlib import Path

from src.db.models import Database, db, use_database


def test_swap_reaches_modules_that_imported_db_at_import_time(tmp_path: Path) -> None:
    from src.agent.tools import memory as memory_tool
    from src.api.routes import kv_store, rouvy

    other = Database(db_path=tmp_path / "other.db")
    try:
        with use_database(other):
            for module in (rouvy, kv_store, memory_tool):
                assert module.db.db_path == other.db_path
        assert db.db_path != other.db_path
    finally:
        other.close()
