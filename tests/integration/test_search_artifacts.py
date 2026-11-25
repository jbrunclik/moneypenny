"""Chat search finds a chat by the title of an artifact built in it (migration 0105).

Artifact titles were not indexed: a chat whose reply built "Wallbox wiring
diagram" was found only if its text happened to say so.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from yoyo import get_backend, read_migrations

from src.db.models.base import MIGRATIONS_DIR

if TYPE_CHECKING:
    from pathlib import Path

    from src.db.models import Database, User
    from src.db.models.dataclasses import SearchResult


def _artifact_hits(db: Database, user: User, query: str) -> list[SearchResult]:
    results, _ = db.search(user.id, query)
    return [r for r in results if r.match_type == "artifact"]


def _built(db: Database, user: User, title: str = "Wallbox wiring diagram") -> tuple[str, str, str]:
    """A chat whose reply built an artifact: (conversation id, message id, artifact id)."""
    conv = db.create_conversation(user.id, "Garage")
    db.add_message(conv.id, "user", "draw it for me")
    message = db.add_message(conv.id, "assistant", "Here it is.")
    artifact, version = db.create_artifact(conv.id, user.id, title, "<svg></svg>")
    db.link_artifact_versions(message.id, [(artifact.id, version.version)])
    return conv.id, message.id, artifact.id


class TestArtifactTitlesAreSearchable:
    def test_a_title_word_finds_the_chat_and_the_message_that_built_it(
        self, test_database: Database, test_user: User
    ) -> None:
        conv_id, message_id, _ = _built(test_database, test_user)

        [hit] = _artifact_hits(test_database, test_user, "wiring")

        assert hit.conversation_id == conv_id
        assert hit.message_id == message_id
        assert hit.message_content is not None
        assert "[[HIGHLIGHT]]wiring[[/HIGHLIGHT]]" in hit.message_content

    def test_renaming_the_chat_keeps_the_artifact_findable(
        self, test_database: Database, test_user: User
    ) -> None:
        conv_id, _, _ = _built(test_database, test_user)
        test_database.update_conversation(conv_id, test_user.id, title="Garáž")

        assert len(_artifact_hits(test_database, test_user, "wiring")) == 1

    def test_a_retitled_artifact_is_found_by_its_new_title(
        self, test_database: Database, test_user: User
    ) -> None:
        _, _, artifact_id = _built(test_database, test_user)
        test_database.revise_artifact(artifact_id, lambda html: html, title="Charger layout")

        assert _artifact_hits(test_database, test_user, "wiring") == []
        assert len(_artifact_hits(test_database, test_user, "charger")) == 1

    def test_deleting_the_reply_drops_its_artifact_from_search(
        self, test_database: Database, test_user: User
    ) -> None:
        _, message_id, _ = _built(test_database, test_user)
        with test_database._pool.get_connection() as conn:
            conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
            conn.commit()

        assert _artifact_hits(test_database, test_user, "wiring") == []
        with test_database._pool.get_connection() as conn:
            orphans = conn.execute(
                "SELECT COUNT(*) FROM search_index_keys WHERE artifact_id IS NOT NULL"
            ).fetchone()[0]
        assert orphans == 0

    def test_other_users_do_not_find_it(self, test_database: Database, test_user: User) -> None:
        _built(test_database, test_user)
        other = test_database.get_or_create_user(email="jana@example.com", name="Jana")

        assert _artifact_hits(test_database, other, "wiring") == []


def _migrate(path: Path, target: str, *, rollback: bool = False) -> None:
    backend = get_backend(f"sqlite:///{path}")
    migrations = read_migrations(str(MIGRATIONS_DIR))
    with backend.lock():
        if rollback:
            backend.rollback_migrations(
                backend.to_rollback(migrations.filter(lambda m: m.id >= target))
            )
        else:
            backend.apply_migrations(backend.to_apply(migrations.filter(lambda m: m.id <= target)))
    backend.connection.close()


class TestMigration0105:
    def test_backfill_indexes_existing_artifacts_and_rollback_removes_them(
        self, test_db_path: Path
    ) -> None:
        _migrate(test_db_path, "0104_projects")
        conn = sqlite3.connect(test_db_path)
        conn.execute(
            """INSERT INTO users (id, email, name, created_at)
               VALUES ('u1', 'a@b.c', 'A', '2026-11-01 00:00:00.000000')"""
        )
        conn.execute(
            """INSERT INTO conversations (id, user_id, title, model, created_at, updated_at)
               VALUES ('c1', 'u1', 'Garage', 'm', '2026-11-01 00:00:00.000000',
                       '2026-11-01 00:00:00.000000')"""
        )
        conn.execute(
            """INSERT INTO messages (id, conversation_id, role, content, created_at)
               VALUES ('m1', 'c1', 'assistant', 'Here it is.', '2026-11-01 00:00:00.000000')"""
        )
        conn.execute(
            """INSERT INTO artifacts (id, conversation_id, user_id, title, created_at, updated_at)
               VALUES ('a1', 'c1', 'u1', 'Wallbox wiring diagram', '2026-11-01 00:00:00',
                       '2026-11-01 00:00:00')"""
        )
        conn.execute(
            """INSERT INTO artifact_versions (artifact_id, version, html, created_by_message_id,
                                              created_at)
               VALUES ('a1', 1, '<svg></svg>', 'm1', '2026-11-01 00:00:00')"""
        )
        conn.commit()
        conn.close()

        _migrate(test_db_path, "0105_search_artifact_titles")
        conn = sqlite3.connect(test_db_path)
        rows = conn.execute(
            """SELECT type, message_id FROM search_index
               WHERE search_index MATCH 'wiring' AND type = 'artifact'"""
        ).fetchall()
        conn.close()
        assert rows == [("artifact", "m1")]

        _migrate(test_db_path, "0105_search_artifact_titles", rollback=True)
        conn = sqlite3.connect(test_db_path)
        left = conn.execute("SELECT COUNT(*) FROM search_index WHERE type = 'artifact'").fetchone()
        columns = [r[1] for r in conn.execute("PRAGMA table_info(search_index_keys)")]
        conn.close()
        assert left == (0,)
        assert "artifact_id" not in columns
