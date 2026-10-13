"""Tests for conversation trash database operations."""

from datetime import datetime, timedelta

from src.db.blob_store import BlobStore
from src.db.models import Database, User, make_blob_key


def _set_deleted_at(db: Database, conv_id: str, when: datetime) -> None:
    with db._pool.get_connection() as conn:
        conn.execute(
            "UPDATE conversations SET deleted_at = ? WHERE id = ?", (when.isoformat(), conv_id)
        )
        conn.commit()


class TestTrashSchema:
    def test_new_conversation_is_live(self, test_database: Database, test_user: User) -> None:
        conv = test_database.create_conversation(test_user.id, "Live")
        loaded = test_database.get_conversation(conv.id, test_user.id)
        assert loaded is not None
        assert loaded.deleted_at is None


class TestTrashOperations:
    def test_trash_hides_and_restore_returns(
        self, test_database: Database, test_user: User
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Doomed")

        assert test_database.trash_conversation(conv.id, test_user.id) is True
        assert all(c.id != conv.id for c in test_database.list_conversations(test_user.id))

        assert test_database.restore_conversation(conv.id, test_user.id) is True
        assert any(c.id == conv.id for c in test_database.list_conversations(test_user.id))

    def test_trash_is_idempotent_and_keeps_deleted_at(
        self, test_database: Database, test_user: User
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Retried")
        earlier = datetime.now() - timedelta(days=3)
        test_database.trash_conversation(conv.id, test_user.id)
        _set_deleted_at(test_database, conv.id, earlier)

        assert test_database.trash_conversation(conv.id, test_user.id) is True

        rows, _, _, _ = test_database.list_trashed_conversations_paginated(test_user.id)
        assert rows[0][0].deleted_at == earlier

    def test_other_users_cannot_trash_or_restore(
        self, test_database: Database, test_user: User
    ) -> None:
        other = test_database.get_or_create_user("other@example.com", "Other")
        conv = test_database.create_conversation(test_user.id, "Mine")

        assert test_database.trash_conversation(conv.id, other.id) is False
        test_database.trash_conversation(conv.id, test_user.id)
        assert test_database.restore_conversation(conv.id, other.id) is False
        assert test_database.delete_trashed_conversation(conv.id, other.id) is False

    def test_restore_keeps_archived_and_pinned(
        self, test_database: Database, test_user: User
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Archived")
        test_database.archive_conversation(conv.id, test_user.id)
        test_database.set_conversation_pinned(conv.id, test_user.id, True)
        test_database.trash_conversation(conv.id, test_user.id)

        test_database.restore_conversation(conv.id, test_user.id)

        restored = test_database.get_conversation(conv.id, test_user.id)
        assert restored is not None
        assert restored.archived is True
        assert restored.pinned is True

    def test_list_trashed_only_returns_trashed(
        self, test_database: Database, test_user: User
    ) -> None:
        live = test_database.create_conversation(test_user.id, "Live")
        trashed = test_database.create_conversation(test_user.id, "Trashed")
        test_database.trash_conversation(trashed.id, test_user.id)

        rows, next_cursor, has_more, total = test_database.list_trashed_conversations_paginated(
            test_user.id
        )

        assert [c.id for c, _, _ in rows] == [trashed.id]
        assert rows[0][0].deleted_at is not None
        assert (next_cursor, has_more, total) == (None, False, 1)
        assert live.id not in [c.id for c, _, _ in rows]

    def test_list_trashed_paginates(self, test_database: Database, test_user: User) -> None:
        ids = []
        for title in ("A", "B", "C"):
            conv = test_database.create_conversation(test_user.id, title)
            test_database.trash_conversation(conv.id, test_user.id)
            ids.append(conv.id)

        first, cursor, has_more, total = test_database.list_trashed_conversations_paginated(
            test_user.id, limit=2
        )
        second, _, more_after, _ = test_database.list_trashed_conversations_paginated(
            test_user.id, limit=2, cursor=cursor
        )

        assert (len(first), has_more, total, more_after) == (2, True, 3, False)
        assert {c.id for c, _, _ in first + second} == set(ids)

    def test_delete_trashed_requires_trash(self, test_database: Database, test_user: User) -> None:
        conv = test_database.create_conversation(test_user.id, "Live")
        assert test_database.delete_trashed_conversation(conv.id, test_user.id) is False

        test_database.trash_conversation(conv.id, test_user.id)
        assert test_database.delete_trashed_conversation(conv.id, test_user.id) is True
        rows, _, _, total = test_database.list_trashed_conversations_paginated(test_user.id)
        assert (rows, total) == ([], 0)

    def test_empty_trash_leaves_live_conversations(
        self, test_database: Database, test_user: User
    ) -> None:
        live = test_database.create_conversation(test_user.id, "Live")
        for title in ("A", "B"):
            conv = test_database.create_conversation(test_user.id, title)
            test_database.trash_conversation(conv.id, test_user.id)

        assert test_database.empty_trash(test_user.id) == 2
        assert [c.id for c in test_database.list_conversations(test_user.id)] == [live.id]

    def test_purge_respects_cutoff_and_deletes_blobs(
        self, test_database: Database, test_user: User, test_blob_store: BlobStore
    ) -> None:
        old = test_database.create_conversation(test_user.id, "Old")
        recent = test_database.create_conversation(test_user.id, "Recent")
        msg = test_database.add_message(
            old.id,
            "user",
            "with file",
            files=[{"name": "a.png", "type": "image/png", "size": 5, "data": "aGVsbG8="}],
        )
        assert test_blob_store.get(make_blob_key(msg.id, 0)) is not None
        for conv in (old, recent):
            test_database.trash_conversation(conv.id, test_user.id)
        _set_deleted_at(test_database, old.id, datetime.now() - timedelta(days=15))
        _set_deleted_at(test_database, recent.id, datetime.now() - timedelta(days=13))

        assert test_database.purge_trashed_conversations(14) == 1

        rows, _, _, _ = test_database.list_trashed_conversations_paginated(test_user.id)
        assert [c.id for c, _, _ in rows] == [recent.id]
        assert test_blob_store.get(make_blob_key(msg.id, 0)) is None


class TestTrashedHiddenEverywhere:
    def _trashed(self, db: Database, user: User) -> str:
        conv = db.create_conversation(user.id, "Secret banana plan")
        db.add_message(conv.id, "user", "banana smoothie recipe")
        db.trash_conversation(conv.id, user.id)
        return conv.id

    def test_get_conversation_returns_none(self, test_database: Database, test_user: User) -> None:
        conv_id = self._trashed(test_database, test_user)
        assert test_database.get_conversation(conv_id, test_user.id) is None
        assert test_database.get_conversation_with_message_count(conv_id) is None

    def test_listings_exclude_trashed(self, test_database: Database, test_user: User) -> None:
        conv_id = self._trashed(test_database, test_user)
        convs, _, _, total = test_database.list_conversations_paginated_with_counts(test_user.id)
        assert conv_id not in [c.id for c, _, _ in convs]
        assert total == 0
        plain, _, _, plain_total = test_database.list_conversations_paginated(test_user.id)
        assert conv_id not in [c.id for c in plain]
        assert plain_total == 0
        with_counts = test_database.list_conversations_with_message_count(test_user.id)
        assert conv_id not in [c.id for c, _, _ in with_counts]
        everything = test_database.list_conversations(test_user.id, include_planning=True)
        assert conv_id not in [c.id for c in everything]

    def test_sync_excludes_trashed(self, test_database: Database, test_user: User) -> None:
        conv_id = self._trashed(test_database, test_user)
        since = datetime.now() - timedelta(hours=1)
        updated = test_database.get_conversations_updated_since(test_user.id, since)
        assert conv_id not in [c.id for c, _, _ in updated]

    def test_pinned_and_archived_lists_exclude_trashed(
        self, test_database: Database, test_user: User
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Pinned")
        test_database.set_conversation_pinned(conv.id, test_user.id, True)
        test_database.trash_conversation(conv.id, test_user.id)
        assert test_database.list_pinned_conversations(test_user.id) == []
        archived = test_database.create_conversation(test_user.id, "Archived")
        test_database.archive_conversation(archived.id, test_user.id)
        test_database.trash_conversation(archived.id, test_user.id)
        rows, _, _, total = test_database.list_archived_conversations_paginated(test_user.id)
        assert (rows, total) == ([], 0)

    def test_organize_ops_ignore_trashed(self, test_database: Database, test_user: User) -> None:
        conv_id = self._trashed(test_database, test_user)
        assert test_database.archive_conversation(conv_id, test_user.id) is False
        assert test_database.unarchive_conversation(conv_id, test_user.id) is False
        assert test_database.set_conversation_pinned(conv_id, test_user.id, True) is False
        assert test_database.update_conversation(conv_id, test_user.id, title="New") is False

    def test_search_excludes_trashed(self, test_database: Database, test_user: User) -> None:
        self._trashed(test_database, test_user)
        results, total = test_database.search(test_user.id, "banana")
        assert (results, total) == ([], 0)

    def test_search_finds_restored(self, test_database: Database, test_user: User) -> None:
        conv_id = self._trashed(test_database, test_user)
        test_database.restore_conversation(conv_id, test_user.id)
        results, _ = test_database.search(test_user.id, "banana")
        assert {r.conversation_id for r in results} == {conv_id}

    def test_message_rows_for_ids_excludes_trashed(
        self, test_database: Database, test_user: User
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Recall")
        msg = test_database.add_message(conv.id, "user", "remember me")
        test_database.trash_conversation(conv.id, test_user.id)
        assert test_database.get_message_rows_for_ids(test_user.id, [msg.id]) == []


def _set_column(db: Database, conv_id: str, column: str, value: object) -> None:
    with db._pool.get_connection() as conn:
        conn.execute(f"UPDATE conversations SET {column} = ? WHERE id = ?", (value, conv_id))
        conn.commit()


class TestBulkTrash:
    def test_trash_conversations_trashes_only_eligible_own_rows(
        self, test_database: Database, test_user: User
    ) -> None:
        other = test_database.get_or_create_user("other@example.com", "Other")
        a = test_database.create_conversation(test_user.id, "A")
        b = test_database.create_conversation(test_user.id, "B")
        agent = test_database.create_conversation(test_user.id, "Agent")
        _set_column(test_database, agent.id, "is_agent", 1)
        foreign = test_database.create_conversation(other.id, "Foreign")

        trashed = test_database.trash_conversations(
            test_user.id, [a.id, b.id, agent.id, foreign.id, "missing"]
        )

        assert sorted(trashed) == sorted([a.id, b.id])
        assert test_database.get_conversation(agent.id, test_user.id) is not None
        assert test_database.get_conversation(foreign.id, other.id) is not None

    def test_trash_conversations_skips_already_trashed(
        self, test_database: Database, test_user: User
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Once")
        earlier = datetime.now() - timedelta(days=3)
        test_database.trash_conversation(conv.id, test_user.id)
        _set_deleted_at(test_database, conv.id, earlier)

        assert test_database.trash_conversations(test_user.id, [conv.id]) == []
        rows, _, _, _ = test_database.list_trashed_conversations_paginated(test_user.id)
        assert rows[0][0].deleted_at == earlier

    def test_trash_conversations_empty_list_is_noop(
        self, test_database: Database, test_user: User
    ) -> None:
        assert test_database.trash_conversations(test_user.id, []) == []

    def test_trash_all_skips_pinned_archived_excluded_special_and_new(
        self, test_database: Database, test_user: User
    ) -> None:
        cutoff = datetime.now()
        plain = test_database.create_conversation(test_user.id, "Plain")
        excluded = test_database.create_conversation(test_user.id, "Excluded")
        pinned = test_database.create_conversation(test_user.id, "Pinned")
        test_database.set_conversation_pinned(pinned.id, test_user.id, True)
        archived = test_database.create_conversation(test_user.id, "Archived")
        test_database.archive_conversation(archived.id, test_user.id)
        sports = test_database.create_conversation(test_user.id, "Sports")
        _set_column(test_database, sports.id, "is_sports", 1)
        newer = test_database.create_conversation(test_user.id, "Newer")
        for conv in (plain, excluded, pinned, archived, sports):
            _set_column(
                test_database, conv.id, "created_at", (cutoff - timedelta(hours=1)).isoformat()
            )
        _set_column(
            test_database, newer.id, "created_at", (cutoff + timedelta(hours=1)).isoformat()
        )

        trashed = test_database.trash_all_conversations(
            test_user.id, exclude_ids=[excluded.id], created_before=cutoff, extra_ids=[]
        )

        assert trashed == [plain.id]

    def test_trash_all_includes_hand_picked_pinned(
        self, test_database: Database, test_user: User
    ) -> None:
        cutoff = datetime.now() + timedelta(seconds=1)
        pinned = test_database.create_conversation(test_user.id, "Pinned")
        test_database.set_conversation_pinned(pinned.id, test_user.id, True)

        trashed = test_database.trash_all_conversations(
            test_user.id, exclude_ids=[], created_before=cutoff, extra_ids=[pinned.id]
        )

        assert trashed == [pinned.id]

    def test_trash_all_is_scoped_to_user(self, test_database: Database, test_user: User) -> None:
        other = test_database.get_or_create_user("other@example.com", "Other")
        foreign = test_database.create_conversation(other.id, "Foreign")
        cutoff = datetime.now() + timedelta(seconds=1)

        assert (
            test_database.trash_all_conversations(
                test_user.id, exclude_ids=[], created_before=cutoff, extra_ids=[foreign.id]
            )
            == []
        )


class TestBulkRestore:
    def test_restore_conversations_returns_only_trashed_own_rows(
        self, test_database: Database, test_user: User
    ) -> None:
        other = test_database.get_or_create_user("other@example.com", "Other")
        trashed = test_database.create_conversation(test_user.id, "Trashed")
        live = test_database.create_conversation(test_user.id, "Live")
        foreign = test_database.create_conversation(other.id, "Foreign")
        test_database.trash_conversation(trashed.id, test_user.id)
        test_database.trash_conversation(foreign.id, other.id)

        restored = test_database.restore_conversations(
            test_user.id, [trashed.id, live.id, foreign.id]
        )

        assert restored == [trashed.id]
        assert test_database.get_conversation(trashed.id, test_user.id) is not None
        assert test_database.get_conversation(foreign.id, other.id) is None


class TestRestoreKeepsListPosition:
    """Undo must put chats back where they were, not lump them at the top."""

    def _three_dated(self, db: Database, user: User) -> list[str]:
        ids = []
        for days_ago, title in ((3, "Old"), (2, "Mid"), (1, "New")):
            conv = db.create_conversation(user.id, title)
            when = (datetime.now() - timedelta(days=days_ago)).isoformat()
            _set_column(db, conv.id, "updated_at", when)
            ids.append(conv.id)
        return ids

    def _updated_at(self, db: Database, conv_id: str) -> str:
        with db._pool.get_connection() as conn:
            return str(
                conn.execute(
                    "SELECT updated_at FROM conversations WHERE id = ?", (conv_id,)
                ).fetchone()["updated_at"]
            )

    def test_bulk_restore_puts_back_original_updated_at(
        self, test_database: Database, test_user: User
    ) -> None:
        ids = self._three_dated(test_database, test_user)
        before = {i: self._updated_at(test_database, i) for i in ids}

        test_database.trash_conversations(test_user.id, ids)
        test_database.restore_conversations(test_user.id, ids)

        assert {i: self._updated_at(test_database, i) for i in ids} == before
        listed = [c.id for c in test_database.list_conversations(test_user.id)]
        assert listed == list(reversed(ids))

    def test_single_restore_puts_back_original_updated_at(
        self, test_database: Database, test_user: User
    ) -> None:
        old_id = self._three_dated(test_database, test_user)[0]
        before = self._updated_at(test_database, old_id)

        test_database.trash_conversation(old_id, test_user.id)
        test_database.restore_conversation(old_id, test_user.id)

        assert self._updated_at(test_database, old_id) == before

    def test_trash_still_bumps_updated_at_for_trash_ordering(
        self, test_database: Database, test_user: User
    ) -> None:
        old_id = self._three_dated(test_database, test_user)[0]
        before = self._updated_at(test_database, old_id)

        test_database.trash_conversations(test_user.id, [old_id])

        assert self._updated_at(test_database, old_id) > before
