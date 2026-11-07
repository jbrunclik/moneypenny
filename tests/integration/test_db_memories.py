"""Integration tests for user memory database operations."""

from __future__ import annotations

import os
import time
from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest

from src.db.models.memory import MemoryWrite, MemoryWriteConflictError

if TYPE_CHECKING:
    from src.db.models import Database, User


@pytest.fixture
def non_utc_timezone() -> Generator[None]:
    """Force a non-UTC local timezone for the duration of a test.

    Timestamp bugs that confuse local time with UTC are invisible on a
    UTC machine (the two values coincide), so tests that care about the
    distinction must pin a zone with a real offset.
    """
    original = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Prague"
    time.tzset()
    yield
    if original is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = original
    time.tzset()


class TestMemoryCrud:
    """Basic memory CRUD operations."""

    def test_add_and_list_memory(self, test_database: Database, test_user: User) -> None:
        """Should store a memory and return it in the listing."""
        memory = test_database.add_memory(test_user.id, "Has a dog named Max", "fact")

        memories = test_database.list_memories(test_user.id)
        assert len(memories) == 1
        assert memories[0].id == memory.id
        assert memories[0].content == "Has a dog named Max"
        assert memories[0].category == "fact"

    def test_get_memory_count(self, test_database: Database, test_user: User) -> None:
        """Should count only this user's memories."""
        test_database.add_memory(test_user.id, "One", "fact")
        test_database.add_memory(test_user.id, "Two", "fact")

        assert test_database.get_memory_count(test_user.id) == 2
        assert test_database.get_memory_count("other-user") == 0


class TestBulkUpdateMemories:
    """Bulk updates used by the nightly defragmentation job."""

    def test_bulk_update_applies_all_three_operations(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should delete, update and add in one transaction."""
        keep = test_database.add_memory(test_user.id, "Keep me", "fact")
        drop = test_database.add_memory(test_user.id, "Drop me", "context")

        result = test_database.bulk_update_memories(
            user_id=test_user.id,
            to_delete=[drop.id],
            to_update=[(keep.id, "Keep me, consolidated", "fact")],
            to_add=[("Brand new consolidated memory", "preference")],
        )

        assert result == {"deleted": 1, "updated": 1, "added": 1}
        contents = {m.content for m in test_database.list_memories(test_user.id)}
        assert contents == {"Keep me, consolidated", "Brand new consolidated memory"}

    @pytest.mark.usefixtures("non_utc_timezone")
    def test_bulk_update_uses_local_time_not_utc(
        self, test_database: Database, test_user: User
    ) -> None:
        """Bulk-updated memories must not get timestamps in the past.

        Regression: bulk_update_memories used datetime.utcnow() while every
        other write used datetime.now(), so each nightly defrag stamped
        updated_at behind created_at by the UTC offset. That broke the
        updated_at DESC ordering and the prompt's "recently updated, leave it
        alone" heuristic.
        """
        memory = test_database.add_memory(test_user.id, "Original content", "fact")

        test_database.bulk_update_memories(
            user_id=test_user.id,
            to_delete=[],
            to_update=[(memory.id, "Updated content", "fact")],
            to_add=[],
        )

        updated = test_database.list_memories(test_user.id)[0]
        assert updated.updated_at >= updated.created_at

    @pytest.mark.usefixtures("non_utc_timezone")
    def test_bulk_added_memories_use_local_time(
        self, test_database: Database, test_user: User
    ) -> None:
        """Memories created by defrag must sort alongside normally-added ones."""
        existing = test_database.add_memory(test_user.id, "Added normally", "fact")

        test_database.bulk_update_memories(
            user_id=test_user.id,
            to_delete=[],
            to_update=[],
            to_add=[("Added by defrag", "fact")],
        )

        by_content = {m.content: m for m in test_database.list_memories(test_user.id)}
        assert by_content["Added by defrag"].created_at >= existing.created_at


class TestSoftDelete:
    """Deletes are recoverable until the nightly purge."""

    def test_delete_hides_memory_but_keeps_row(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should disappear from the live listing but stay restorable."""
        memory = test_database.add_memory(test_user.id, "Delete me", "context")

        assert test_database.delete_memory(memory.id, test_user.id) is True
        assert test_database.list_memories(test_user.id) == []
        assert test_database.get_memory_count(test_user.id) == 0

        deleted = test_database.list_deleted_memories(test_user.id)
        assert [m.id for m in deleted] == [memory.id]
        assert deleted[0].deleted_at is not None

    def test_restore_brings_memory_back(self, test_database: Database, test_user: User) -> None:
        """Should return a soft-deleted memory to the live listing."""
        memory = test_database.add_memory(test_user.id, "Restore me", "fact")
        test_database.delete_memory(memory.id, test_user.id)

        assert test_database.restore_memory(memory.id, test_user.id) is True
        assert [m.id for m in test_database.list_memories(test_user.id)] == [memory.id]
        assert test_database.list_deleted_memories(test_user.id) == []

    def test_restore_live_memory_is_noop(self, test_database: Database, test_user: User) -> None:
        """Should not report success for a memory that was never deleted."""
        memory = test_database.add_memory(test_user.id, "Live", "fact")

        assert test_database.restore_memory(memory.id, test_user.id) is False

    def test_purge_removes_only_expired_rows(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should hard-delete rows past retention and keep fresh ones."""
        fresh = test_database.add_memory(test_user.id, "Recently deleted", "fact")
        test_database.delete_memory(fresh.id, test_user.id)

        assert test_database.purge_deleted_memories(retention_days=7) == 0
        assert len(test_database.list_deleted_memories(test_user.id)) == 1

        # retention_days=0 puts the cutoff at "now", expiring the row
        assert test_database.purge_deleted_memories(retention_days=0) == 1
        assert test_database.list_deleted_memories(test_user.id) == []

    def test_purge_leaves_live_memories_alone(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should never touch memories that were not deleted."""
        test_database.add_memory(test_user.id, "Live memory", "fact")

        assert test_database.purge_deleted_memories(retention_days=0) == 0
        assert len(test_database.list_memories(test_user.id)) == 1


class TestProtectedMemories:
    """Protection makes the never-delete rule an invariant, not a prompt hope."""

    def test_protected_memory_survives_llm_delete(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should refuse deletion without allow_protected."""
        memory = test_database.add_memory(
            test_user.id, "Wife's name is Sarah", "fact", protected=True
        )

        assert test_database.delete_memory(memory.id, test_user.id) is False
        assert [m.id for m in test_database.list_memories(test_user.id)] == [memory.id]

    def test_user_can_delete_protected_memory(
        self, test_database: Database, test_user: User
    ) -> None:
        """The user owns the protection flag, so their own delete wins."""
        memory = test_database.add_memory(test_user.id, "Protected", "fact", protected=True)

        assert test_database.delete_memory(memory.id, test_user.id, allow_protected=True) is True
        assert test_database.list_memories(test_user.id) == []

    def test_protected_memory_survives_defrag(
        self, test_database: Database, test_user: User
    ) -> None:
        """Bulk deletes from defragmentation must skip protected memories."""
        protected = test_database.add_memory(test_user.id, "Allergic to shellfish", "fact")
        test_database.set_memory_protected(protected.id, test_user.id, True)
        disposable = test_database.add_memory(test_user.id, "Asked about the weather", "context")

        result = test_database.bulk_update_memories(
            user_id=test_user.id,
            to_delete=[protected.id, disposable.id],
            to_update=[],
            to_add=[],
        )

        assert result["deleted"] == 1
        remaining = [m.id for m in test_database.list_memories(test_user.id)]
        assert remaining == [protected.id]

    def test_set_protection_roundtrip(self, test_database: Database, test_user: User) -> None:
        """Should toggle protection on and off."""
        memory = test_database.add_memory(test_user.id, "Toggle me", "fact")
        assert memory.protected is False

        assert test_database.set_memory_protected(memory.id, test_user.id, True) is True
        assert test_database.get_memory(memory.id, test_user.id).protected is True

        assert test_database.set_memory_protected(memory.id, test_user.id, False) is True
        assert test_database.get_memory(memory.id, test_user.id).protected is False


class TestMemoryProvenance:
    """Memories record which conversation taught them."""

    def test_source_conversation_is_stored(self, test_database: Database, test_user: User) -> None:
        """Should round-trip source_conversation_id."""
        conv = test_database.create_conversation(test_user.id, "Where it was learned")
        memory = test_database.add_memory(
            test_user.id, "Runs marathons", "context", source_conversation_id=conv.id
        )

        stored = test_database.get_memory(memory.id, test_user.id)
        assert stored.source_conversation_id == conv.id

    def test_source_conversation_defaults_to_none(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should tolerate memories with no known source."""
        memory = test_database.add_memory(test_user.id, "No provenance", "fact")

        assert test_database.get_memory(memory.id, test_user.id).source_conversation_id is None


class TestUsersWithMemoryCounts:
    """Query used to pick defragmentation candidates."""

    def test_respects_minimum_threshold(self, test_database: Database, test_user: User) -> None:
        """Should exclude users below the minimum memory count."""
        test_database.add_memory(test_user.id, "Only one", "fact")

        assert test_database.get_users_with_memory_counts(min_memories=2) == []

        results = test_database.get_users_with_memory_counts(min_memories=1)
        assert [(u.id, count) for u, count in results] == [(test_user.id, 1)]


class TestApplyMemoryBatch:
    """manage_memory's batch lands in one transaction: all of it or none."""

    def test_applies_add_patch_and_delete_together(
        self, test_database: Database, test_user: User
    ) -> None:
        kept = test_database.add_memory(test_user.id, "Likes coffee", "preference")
        gone = test_database.add_memory(test_user.id, "Old note", "context")

        new_ids = test_database.apply_memory_batch(
            test_user.id,
            "conv-1",
            [
                MemoryWrite(
                    "patch",
                    memory_id=kept.id,
                    content="Likes dark roast coffee",
                    expected="Likes coffee",
                    category="fact",
                ),
                MemoryWrite("delete", memory_id=gone.id),
                MemoryWrite("add", content="Has a dog", category="fact"),
            ],
        )

        memories = {m.id: m for m in test_database.list_memories(test_user.id)}
        assert memories[kept.id].content == "Likes dark roast coffee"
        assert memories[kept.id].category == "fact"
        assert gone.id not in memories
        assert new_ids[0] is None and new_ids[1] is None
        added = memories[str(new_ids[2])]
        assert (added.content, added.source_conversation_id) == ("Has a dog", "conv-1")

    def test_stale_patch_rolls_back_the_whole_batch(
        self, test_database: Database, test_user: User
    ) -> None:
        """A memory edited after the batch was planned must not be overwritten."""
        memory = test_database.add_memory(test_user.id, "Likes coffee", "preference")

        with pytest.raises(MemoryWriteConflictError) as excinfo:
            test_database.apply_memory_batch(
                test_user.id,
                None,
                [
                    MemoryWrite("add", content="Never stored", category="fact"),
                    MemoryWrite("patch", memory_id=memory.id, content="X", expected="Likes tea"),
                ],
            )

        assert excinfo.value.memory_id == memory.id
        assert [m.content for m in test_database.list_memories(test_user.id)] == ["Likes coffee"]

    def test_another_users_memory_is_a_conflict(
        self, test_database: Database, test_user: User
    ) -> None:
        memory = test_database.add_memory(test_user.id, "Likes coffee", "preference")

        with pytest.raises(MemoryWriteConflictError):
            test_database.apply_memory_batch(
                "other-user",
                None,
                [
                    MemoryWrite(
                        "patch", memory_id=memory.id, content="Hijacked", expected="Likes coffee"
                    )
                ],
            )

        assert test_database.list_memories(test_user.id)[0].content == "Likes coffee"

    def test_deleted_memory_cannot_be_patched(
        self, test_database: Database, test_user: User
    ) -> None:
        memory = test_database.add_memory(test_user.id, "Gone", "fact")
        test_database.delete_memory(memory.id, test_user.id)

        with pytest.raises(MemoryWriteConflictError):
            test_database.apply_memory_batch(
                test_user.id,
                None,
                [MemoryWrite("patch", memory_id=memory.id, content="Back", expected="Gone")],
            )

    def test_protected_memory_delete_is_a_conflict(
        self, test_database: Database, test_user: User
    ) -> None:
        memory = test_database.add_memory(test_user.id, "Allergic", "fact", protected=True)

        with pytest.raises(MemoryWriteConflictError):
            test_database.apply_memory_batch(
                test_user.id, None, [MemoryWrite("delete", memory_id=memory.id)]
            )

        assert len(test_database.list_memories(test_user.id)) == 1
