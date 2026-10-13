"""The search index's lookup table (migration 0067).

search_index (FTS5) has only UNINDEXED id columns, so the triggers' deletes by
message_id / conversation_id scanned the whole index for every deleted
message - quadratic for bulk deletes (Oct 13 2026: a 1000-chat empty trash
took minutes). search_index_keys maps ids to FTS rowids so they hit one row.
"""

import sqlite3
from pathlib import Path

from yoyo import get_backend, read_migrations

from src.db.models import Database, User
from src.db.models.base import MIGRATIONS_DIR


def _keys(db: Database) -> set[tuple[int, str, str | None]]:
    with db._pool.get_connection() as conn:
        return {
            (r["fts_rowid"], r["conversation_id"], r["message_id"])
            for r in conn.execute(
                "SELECT fts_rowid, conversation_id, message_id FROM search_index_keys"
            )
        }


def _index(db: Database) -> set[tuple[int, str, str | None]]:
    with db._pool.get_connection() as conn:
        return {
            (r["rid"], r["conversation_id"], r["message_id"])
            for r in conn.execute(
                "SELECT rowid AS rid, conversation_id, message_id FROM search_index"
            )
        }


def _hits(db: Database, user: User, query: str) -> set[str]:
    results, _ = db.search(user.id, query)
    return {r.message_id or f"conv:{r.conversation_id}" for r in results}


class TestKeysTrackTheIndex:
    def test_every_index_row_has_its_key(self, test_database: Database, test_user: User) -> None:
        conv = test_database.create_conversation(test_user.id, "Banana bread")
        test_database.add_message(conv.id, "user", "how long to bake banana bread")
        test_database.add_message(conv.id, "assistant", "about an hour")

        assert _keys(test_database) == _index(test_database)
        assert len(_keys(test_database)) == 3

    def test_deleting_a_message_unindexes_it(
        self, test_database: Database, test_user: User
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Chat")
        keep = test_database.add_message(conv.id, "user", "kiwi smoothie")
        gone = test_database.add_message(conv.id, "assistant", "kiwi sorbet")

        test_database.delete_message(gone.id, test_user.id)

        assert _hits(test_database, test_user, "kiwi") == {keep.id}
        assert _keys(test_database) == _index(test_database)

    def test_rename_reindexes_the_title(self, test_database: Database, test_user: User) -> None:
        conv = test_database.create_conversation(test_user.id, "Old walrus title")
        test_database.update_conversation(conv.id, test_user.id, title="New pelican title")

        assert _hits(test_database, test_user, "walrus") == set()
        assert _hits(test_database, test_user, "pelican") == {f"conv:{conv.id}"}
        assert _keys(test_database) == _index(test_database)

    def test_deleting_a_conversation_unindexes_everything(
        self, test_database: Database, test_user: User
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Mango plans")
        test_database.add_message(conv.id, "user", "mango lassi")
        other = test_database.create_conversation(test_user.id, "Other")

        test_database.delete_conversation(conv.id, test_user.id)

        assert _hits(test_database, test_user, "mango") == set()
        assert {k[1] for k in _keys(test_database)} == {other.id}
        assert _keys(test_database) == _index(test_database)

    def test_agent_conversations_stay_unindexed(
        self, test_database: Database, test_user: User
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Agent")
        with test_database._pool.get_connection() as conn:
            conn.execute("UPDATE conversations SET is_agent = 1 WHERE id = ?", (conv.id,))
            conn.commit()
        test_database.add_message(conv.id, "user", "papaya report")

        assert _hits(test_database, test_user, "papaya") == set()
        assert _keys(test_database) == _index(test_database)


def test_migration_backfills_keys_from_an_existing_index(tmp_path: Path) -> None:
    """A database indexed before 0067 gets a key for every existing row."""
    db_path = tmp_path / "pre.db"
    backend = get_backend(f"sqlite:///{db_path}")
    migrations = read_migrations(str(MIGRATIONS_DIR))
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations.filter(lambda m: m.id < "0067")))
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO users (id, email, name, created_at) VALUES ('u', 'u@x', 'U', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO conversations (id, user_id, title, model, created_at, updated_at)"
        " VALUES ('c', 'u', 'Quince jam', 'm', '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO messages (id, conversation_id, role, content, created_at)"
        " VALUES ('m', 'c', 'user', 'quince paste', '2026-01-01')"
    )
    conn.commit()
    before = {
        r[0:3] for r in conn.execute("SELECT rowid, conversation_id, message_id FROM search_index")
    }
    # Some older databases indexed a message twice (200 such rows in a dev
    # copy): the backfill keeps one, so search stops returning it twice
    conn.execute(
        "INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)"
        " VALUES ('u', 'c', 'm', 'message', '', 'quince paste')"
    )
    conn.commit()
    conn.close()

    db = Database(db_path=db_path)  # applies 0067
    try:
        assert _keys(db) == before == _index(db)
        assert len(db.search("u", "quince")[0]) == 2  # the title and the message, once each
        db.delete_conversation("c", "u")
        assert _keys(db) == set() == _index(db)
    finally:
        db.close()
