# Conversation Trash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deleting a conversation moves it to a trash, restorable for 14 days, after which the daily sweep purges it.

**Architecture:** A nullable `conversations.deleted_at` column marks trashed rows. Every user-facing query filters `deleted_at IS NULL`; a new `ConversationTrashMixin` owns trash/restore/list/purge and delegates the real deletion to the existing hard `delete_conversation`. The frontend gains a Trash view modeled on the Archive view.

**Tech Stack:** Flask + APIFlask + Pydantic, SQLite + yoyo migrations, pytest; vanilla TypeScript + Zustand, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-01-conversation-trash-design.md`

## Global Constraints

- Retention: `TRASH_RETENTION_DAYS` env var, default `14`, in `src/config.py` and `.env.example`.
- Only regular chats are trashed. Agent, planner, sports and language conversations keep the immediate hard delete.
- Timestamps are naive local ISO strings (`datetime.now().isoformat()`), like `updated_at`.
- Dialog copy: title "Move to trash", message "Move this conversation to the trash? You can restore it for 14 days.", confirm "Move to trash". Toast "Moved to trash." with an "Undo" action.
- Public repo: no infra details in code, docs or commits.
- Before each commit: `make lint` and `make test-all` green, checked by exit code (log to a file, branch on `$?`).
- Work on branch `feat/conversation-trash`; Conventional Commits.
- Spec deviation (decided while planning): trash and restore are idempotent (a retried request returns 200 rather than 404, because the API client retries DELETE/POST). The spec is updated in Task 9.

## Review Focus

1. A retried `DELETE` (network retry after a lost response) must not 404 or reset the retention clock. Test: `test_trash_is_idempotent_and_keeps_deleted_at` (Task 2).
2. Restoring an archived chat must return it to the archive, not the main list. Tests: `test_restore_keeps_archived_and_pinned` (Task 2), and the frontend restore branch (Task 7).
3. A trashed chat must not leak through search or semantic recall (the `conversation_search` agent tool). Tests: `test_search_excludes_trashed`, `test_message_rows_for_ids_excludes_trashed` (Task 3).
4. The purge must only remove chats past the cutoff and must also delete their blobs. Test: `test_purge_respects_cutoff_and_deletes_blobs` (Task 2).
5. Agent and program conversations deleted via `DELETE /conversations/<id>` must still be hard-deleted, not trashed. Test: `test_delete_agent_conversation_is_hard_delete` (Task 4).

---

### Task 1: Schema, dataclass, config

**Files:**
- Create: `migrations/0056_add_conversation_trash.py`
- Modify: `src/db/models/dataclasses.py` (Conversation), `src/db/models/conversation_rows.py` (`row_to_conversation`), `src/config.py` (beside retention settings ~line 247), `.env.example` (~line 137)
- Test: `tests/integration/test_db_conversation_trash.py` (new)

**Interfaces:**
- Produces: `Conversation.deleted_at: datetime | None`; `Config.TRASH_RETENTION_DAYS: int`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for conversation trash database operations."""

from datetime import datetime, timedelta

from src.db.models import Database, User


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
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/integration/test_db_conversation_trash.py -v`
Expected: FAIL with `AttributeError: 'Conversation' object has no attribute 'deleted_at'`

- [ ] **Step 3: Implement**

`migrations/0056_add_conversation_trash.py`:

```python
"""Add trash support for conversations.

deleted_at marks a conversation as in the trash (NULL = live). Trashed rows
are hidden from every user-facing query and purged by the daily cleanup
sweep after TRASH_RETENTION_DAYS.
"""

from yoyo import step

__depends__ = {"0055_add_message_stop_reason"}

steps = [
    step(
        "ALTER TABLE conversations ADD COLUMN deleted_at TEXT",
        "ALTER TABLE conversations DROP COLUMN deleted_at",
    ),
    step(
        "CREATE INDEX IF NOT EXISTS idx_conversations_user_deleted"
        " ON conversations(user_id, deleted_at)",
        "DROP INDEX IF EXISTS idx_conversations_user_deleted",
    ),
]
```

In `Conversation`, after `anonymous_mode`:

```python
    # Set while the conversation is in the trash (NULL = live)
    deleted_at: datetime | None = None
```

In `row_to_conversation`, beside the other optional columns, and pass `deleted_at=deleted_at` into the constructor:

```python
    deleted_at = None
    if "deleted_at" in row.keys():
        deleted_at = datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None
```

`src/config.py`, after `FILE_RETENTION_DAYS`:

```python
    # Deleted conversations stay restorable in the trash this long
    TRASH_RETENTION_DAYS: int = int(os.getenv("TRASH_RETENTION_DAYS", "14"))
```

`.env.example`, after `FILE_RETENTION_DAYS=30`:

```
# Days a deleted conversation stays restorable in the trash
TRASH_RETENTION_DAYS=14
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `.venv/bin/pytest tests/integration/test_db_conversation_trash.py -v`
Expected: PASS

### Task 2: Trash mixin (trash, restore, list, permanent delete, empty, purge)

**Files:**
- Create: `src/db/models/conversation_trash.py`
- Modify: `src/db/models/__init__.py` (import; add `ConversationTrashMixin` after `ConversationArchiveMixin` in `Database` bases), `src/db/models/conversation.py` docstring (mention conversation_trash.py)
- Test: `tests/integration/test_db_conversation_trash.py`

**Interfaces:**
- Consumes: `Conversation.deleted_at`; `ConversationMixin.delete_conversation(conv_id, user_id) -> bool` (hard delete, blob cleanup).
- Produces:
  - `trash_conversation(conv_id: str, user_id: str) -> bool`
  - `restore_conversation(conv_id: str, user_id: str) -> bool`
  - `list_trashed_conversations_paginated(user_id: str, limit: int = 30, cursor: str | None = None) -> tuple[list[tuple[Conversation, int, str | None]], str | None, bool, int]`
  - `delete_trashed_conversation(conv_id: str, user_id: str) -> bool`
  - `empty_trash(user_id: str) -> int`
  - `purge_trashed_conversations(retention_days: int) -> int`

- [ ] **Step 1: Write the failing tests** (append to the test file)

```python
class TestTrashOperations:
    def test_trash_hides_and_restore_returns(self, test_database: Database, test_user: User) -> None:
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
        self, test_database: Database, test_user: User, test_blob_store
    ) -> None:
        old = test_database.create_conversation(test_user.id, "Old")
        recent = test_database.create_conversation(test_user.id, "Recent")
        msg = test_database.add_message(
            old.id, "user", "with file",
            files=[{"name": "a.png", "type": "image/png", "data": "aGVsbG8="}],
        )
        for conv in (old, recent):
            test_database.trash_conversation(conv.id, test_user.id)
        _set_deleted_at(test_database, old.id, datetime.now() - timedelta(days=15))
        _set_deleted_at(test_database, recent.id, datetime.now() - timedelta(days=13))

        assert test_database.purge_trashed_conversations(14) == 1

        rows, _, _, _ = test_database.list_trashed_conversations_paginated(test_user.id)
        assert [c.id for c, _, _ in rows] == [recent.id]
        from src.db.models import make_blob_key
        assert test_blob_store.get(make_blob_key(msg.id, 0)) is None
```

Before writing these, check the exact signatures of `get_or_create_user`, `add_message` (the `files=` shape) and the `test_blob_store` fixture (`get` vs `exists`) in `tests/conftest.py` and `tests/unit/test_file_retention.py::_seed`, and adapt the calls. Don't change the assertions.

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/pytest tests/integration/test_db_conversation_trash.py -v`
Expected: FAIL with `AttributeError: 'Database' object has no attribute 'trash_conversation'`

- [ ] **Step 3: Implement `src/db/models/conversation_trash.py`**

```python
"""Conversation trash database operations mixin.

Deleting a chat from the UI moves it to the trash (deleted_at set) instead
of destroying it. It stays restorable until the daily cleanup sweep purges
it after TRASH_RETENTION_DAYS. The real deletion (rows, then blobs) is
ConversationMixin.delete_conversation.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.db.models.conversation_rows import page_rows, row_to_conversation_summary
from src.db.models.dataclasses import Conversation
from src.db.models.helpers import parse_cursor
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)

_TRASH_LIST_SELECT = """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                          c.is_planning, c.archived, c.pinned, c.deleted_at,
                          COUNT(m.id) as message_count,
                          (SELECT m2.content FROM messages m2
                           WHERE m2.conversation_id = c.id
                           ORDER BY m2.created_at DESC, m2.id DESC LIMIT 1) as last_message
                   FROM conversations c
                   LEFT JOIN messages m ON m.conversation_id = c.id
                   WHERE c.user_id = ? AND c.deleted_at IS NOT NULL"""


class ConversationTrashMixin:
    """Mixin providing conversation trash, restore and purge operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def delete_conversation(self, conv_id: str, user_id: str) -> bool:
        """Hard delete (defined in ConversationMixin)."""
        raise NotImplementedError

    def trash_conversation(self, conv_id: str, user_id: str) -> bool:
        """Move a conversation to the trash.

        Idempotent: trashing an already-trashed conversation succeeds and
        keeps the original deleted_at, so a retried DELETE neither 404s nor
        extends the retention window. updated_at is bumped so incremental
        sync on other devices sees the change.
        """
        now = datetime.now().isoformat()
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE conversations
                   SET deleted_at = COALESCE(deleted_at, ?), updated_at = ?
                   WHERE id = ? AND user_id = ?""",
                (now, now, conv_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def restore_conversation(self, conv_id: str, user_id: str) -> bool:
        """Take a conversation out of the trash, back where it was.

        archived/pinned are untouched, so an archived chat returns to the
        archive. Idempotent for live conversations (True, no change).
        """
        now = datetime.now().isoformat()
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE conversations
                   SET updated_at = CASE WHEN deleted_at IS NULL THEN updated_at ELSE ? END,
                       deleted_at = NULL
                   WHERE id = ? AND user_id = ?""",
                (now, conv_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_trashed_conversations_paginated(
        self,
        user_id: str,
        limit: int = 30,
        cursor: str | None = None,
    ) -> tuple[list[tuple[Conversation, int, str | None]], str | None, bool, int]:
        """Trashed conversations, most recently trashed first.

        Same shape as list_archived_conversations_paginated. Trashing bumps
        updated_at, so the shared (updated_at, id) cursor orders by trash time.
        """
        with self._pool.get_connection() as conn:
            total_row = self._execute_with_timing(
                conn,
                """SELECT COUNT(*) as count FROM conversations
                   WHERE user_id = ? AND deleted_at IS NOT NULL""",
                (user_id,),
            ).fetchone()
            total_count = int(total_row["count"]) if total_row else 0

            if cursor:
                cursor_timestamp, cursor_id = parse_cursor(cursor)
                query = (
                    _TRASH_LIST_SELECT
                    + " AND (c.updated_at < ? OR (c.updated_at = ? AND c.id < ?))"
                )
                params: tuple[Any, ...] = (user_id, cursor_timestamp, cursor_timestamp, cursor_id)
            else:
                query = _TRASH_LIST_SELECT
                params = (user_id,)
            rows = self._execute_with_timing(
                conn,
                query + " GROUP BY c.id ORDER BY c.updated_at DESC, c.id DESC LIMIT ?",
                (*params, limit + 1),
            ).fetchall()

        rows, next_cursor, has_more = page_rows(rows, limit)
        return [row_to_conversation_summary(row) for row in rows], next_cursor, has_more, total_count

    def delete_trashed_conversation(self, conv_id: str, user_id: str) -> bool:
        """Permanently delete one conversation, only if it is in the trash."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT 1 FROM conversations
                   WHERE id = ? AND user_id = ? AND deleted_at IS NOT NULL""",
                (conv_id, user_id),
            ).fetchone()
        if not row:
            return False
        return self.delete_conversation(conv_id, user_id)

    def empty_trash(self, user_id: str) -> int:
        """Permanently delete all of a user's trashed conversations."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                "SELECT id FROM conversations WHERE user_id = ? AND deleted_at IS NOT NULL",
                (user_id,),
            ).fetchall()
        return sum(1 for row in rows if self.delete_conversation(row["id"], user_id))

    def purge_trashed_conversations(self, retention_days: int) -> int:
        """Permanently delete conversations trashed over retention_days ago (all users)."""
        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT id, user_id FROM conversations
                   WHERE deleted_at IS NOT NULL AND deleted_at < ?""",
                (cutoff,),
            ).fetchall()
        purged = sum(1 for row in rows if self.delete_conversation(row["id"], row["user_id"]))
        if purged:
            logger.info("Purged trashed conversations", extra={"purged": purged})
        return purged
```

Register it in `src/db/models/__init__.py`: add the import, then put `ConversationTrashMixin,` right after `ConversationArchiveMixin,` in the `Database` bases. `ConversationMixin` comes earlier in the MRO, so its real `delete_conversation` overrides the stub.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/integration/test_db_conversation_trash.py -v`
Expected: PASS (`test_trash_hides_and_restore_returns` passes only after Task 3 adds the list filter. If it fails here on the `list_conversations` assertion, carry on and it will go green in Task 3.)

### Task 3: Hide trashed conversations from every live query

**Files:**
- Modify:
  - `src/db/models/conversation.py`: `get_conversation` (~line 83), `list_conversations` (both branches, ~lines 109/116), `get_conversation_with_message_count` (~line 258).
  - `src/db/models/conversation_listing.py`: every query that has the `archived` filter (lines ~67, 84, 97, 141, 161, 184, 246, 303).
  - `src/db/models/conversation_archive.py`: `list_pinned_conversations`, `list_archived_conversations_paginated` (count and both selects), `archive_conversation`, `unarchive_conversation`, `set_conversation_pinned`.
  - `src/db/models/conversation.py`: `update_conversation` (the WHERE clause, so a rename can't touch a trashed chat).
  - `src/db/models/search.py` (`search` WHERE clause).
  - `src/db/models/embeddings.py` (`get_message_rows_for_ids` WHERE clause).
- Test: `tests/integration/test_db_conversation_trash.py`

**Interfaces:**
- Produces: the invariant that a trashed conversation is invisible to `get_conversation`, all listings, sync queries, search and semantic recall. Trash-mixin methods are the only readers of trashed rows.

- [ ] **Step 1: Write the failing tests**

```python
class TestTrashedHiddenEverywhere:
    def _trashed(self, db: Database, user: User) -> str:
        conv = db.create_conversation(user.id, "Secret banana plan")
        db.add_message(conv.id, "user", "banana smoothie recipe")
        db.trash_conversation(conv.id, user.id)
        return conv.id

    def test_get_conversation_returns_none(self, test_database: Database, test_user: User) -> None:
        conv_id = self._trashed(test_database, test_user)
        assert test_database.get_conversation(conv_id, test_user.id) is None

    def test_listings_exclude_trashed(self, test_database: Database, test_user: User) -> None:
        conv_id = self._trashed(test_database, test_user)
        convs, _, _, total = test_database.list_conversations_paginated_with_counts(test_user.id)
        assert conv_id not in [c.id for c, _, _ in convs]
        assert total == 0
        plain, _, _, plain_total = test_database.list_conversations_paginated(test_user.id)
        assert conv_id not in [c.id for c in plain] and plain_total == 0
        assert conv_id not in [c.id for c, _ in test_database.list_conversations_with_message_count(test_user.id)]

    def test_sync_excludes_trashed(self, test_database: Database, test_user: User) -> None:
        conv_id = self._trashed(test_database, test_user)
        since = datetime.now() - timedelta(hours=1)
        updated = test_database.get_conversations_updated_since(test_user.id, since)
        assert conv_id not in [c.id for c, *_ in updated]

    def test_pinned_and_archived_lists_exclude_trashed(
        self, test_database: Database, test_user: User
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Pinned archived")
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
```

Check the real return shapes of `list_conversations_with_message_count`, `get_conversations_updated_since` and `SearchResult.conversation_id` in the mixins, and adjust the unpacking. Don't change what's being asserted.

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/pytest tests/integration/test_db_conversation_trash.py -k Hidden -v`
Expected: several FAIL (the trashed chat is still returned).

- [ ] **Step 3: Implement the filters**

- Next to every existing `AND (archived = 0 OR archived IS NULL)` / `AND (c.archived = 0 OR c.archived IS NULL)` in `conversation_listing.py` and `conversation.py::list_conversations`, add `AND deleted_at IS NULL` (or `AND c.deleted_at IS NULL` when aliased). Add it to the `include_planning=True` branch of `list_conversations` too.
- `get_conversation`: `"SELECT * FROM conversations WHERE id = ? AND user_id = ? AND deleted_at IS NULL"`.
- `get_conversation_with_message_count`: `WHERE c.id = ? AND c.deleted_at IS NULL`.
- `update_conversation`: `f"UPDATE conversations SET {', '.join(updates)} WHERE id = ? AND user_id = ? AND deleted_at IS NULL"`.
- `conversation_archive.py`: add `AND deleted_at IS NULL` to the UPDATEs in `archive_conversation`, `unarchive_conversation` and `set_conversation_pinned`; add `AND c.deleted_at IS NULL` (or `AND deleted_at IS NULL` in the count) to `list_pinned_conversations` and all three queries of `list_archived_conversations_paginated`.
- `search.py`: `WHERE si.user_id = ? AND search_index MATCH ? AND c.deleted_at IS NULL`.
- `embeddings.py::get_message_rows_for_ids`: `WHERE c.user_id = ? AND c.deleted_at IS NULL AND m.id IN (...)`.

Don't touch `delete_conversation`, `programs.py`, `planner.py`, `agent*.py` or `message.py:292` (the embedding enqueue lookup). Those keep reading by id.

- [ ] **Step 4: Run the trash tests and the existing DB and search suites**

Run: `.venv/bin/pytest tests/integration/test_db_conversation_trash.py tests/integration/test_db_models.py tests/integration/test_routes_search.py tests/unit/test_conversation_search_tool.py -v`
Expected: PASS

### Task 4: API routes and schemas

**Files:**
- Create: `src/api/routes/conversation_trash.py`
- Modify:
  - `src/api/routes/conversations.py`: `delete_conversation` (~line 312).
  - `src/api/routes/__init__.py`: the route docstring list, plus the import that registers the module. Mirror how `conversation_organize` is imported.
  - `src/api/schemas/conversations.py`: `ConversationResponse` gets `deleted_at`/`purge_at`, plus a new `EmptyTrashResponse`.
- Regenerate: `static/openapi.json` (`make openapi`), `web/src/types/generated-api.ts` (`make types`). Never hand-edit either file.
- Test: `tests/integration/test_routes_conversation_trash.py` (new); update `tests/integration/test_routes_conversations.py::TestDeleteConversation`.

**Interfaces:**
- Consumes: the Task 2 mixin methods, `Config.TRASH_RETENTION_DAYS`.
- Produces (HTTP):
  - `DELETE /api/conversations/<id>` → `{"status": "trashed"}` (regular chat) or `{"status": "deleted"}` (agent, planner, sports or language chat, which is hard-deleted); 404 if missing.
  - `GET /api/conversations/trash?limit=&cursor=` → `ConversationsListPaginatedResponse`. Each item has `deleted_at` and `purge_at` (ISO strings) and `archived`.
  - `POST /api/conversations/<id>/restore` → `{"status": "restored"}`; 404 if missing.
  - `DELETE /api/conversations/<id>/permanent` → `{"status": "deleted"}`; 404 if not in the trash.
  - `DELETE /api/conversations/trash` → `{"deleted": <int>}`.

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_routes_conversation_trash.py`:

```python
"""Tests for the conversation trash routes."""

from datetime import datetime, timedelta

from flask.testing import FlaskClient

from src.db.models import Conversation, Database, User


def _trash(client: FlaskClient, headers: dict[str, str], conv_id: str) -> None:
    response = client.delete(f"/api/conversations/{conv_id}", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["status"] == "trashed"


class TestTrashRoutes:
    def test_delete_moves_to_trash(
        self, client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
    ) -> None:
        _trash(client, auth_headers, test_conversation.id)

        assert client.get(f"/api/conversations/{test_conversation.id}", headers=auth_headers).status_code == 404
        data = client.get("/api/conversations/trash", headers=auth_headers).get_json()
        assert [c["id"] for c in data["conversations"]] == [test_conversation.id]
        item = data["conversations"][0]
        deleted_at = datetime.fromisoformat(item["deleted_at"])
        assert datetime.fromisoformat(item["purge_at"]) - deleted_at == timedelta(days=14)
        assert data["pagination"]["total_count"] == 1

    def test_delete_twice_is_ok(
        self, client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
    ) -> None:
        _trash(client, auth_headers, test_conversation.id)
        _trash(client, auth_headers, test_conversation.id)

    def test_restore(
        self, client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
    ) -> None:
        _trash(client, auth_headers, test_conversation.id)
        response = client.post(f"/api/conversations/{test_conversation.id}/restore", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json()["status"] == "restored"
        assert client.get(f"/api/conversations/{test_conversation.id}", headers=auth_headers).status_code == 200

    def test_restore_missing_404(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        assert client.post("/api/conversations/nope/restore", headers=auth_headers).status_code == 404

    def test_permanent_delete_requires_trash(
        self, client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
    ) -> None:
        url = f"/api/conversations/{test_conversation.id}/permanent"
        assert client.delete(url, headers=auth_headers).status_code == 404
        _trash(client, auth_headers, test_conversation.id)
        assert client.delete(url, headers=auth_headers).status_code == 200
        assert client.get("/api/conversations/trash", headers=auth_headers).get_json()["conversations"] == []

    def test_empty_trash(
        self, client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
    ) -> None:
        for title in ("A", "B"):
            conv = test_database.create_conversation(test_user.id, title)
            _trash(client, auth_headers, conv.id)
        response = client.delete("/api/conversations/trash", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json() == {"deleted": 2}

    def test_delete_agent_conversation_is_hard_delete(
        self, client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Agent")
        with test_database._pool.get_connection() as conn:
            conn.execute("UPDATE conversations SET is_agent = 1 WHERE id = ?", (conv.id,))
            conn.commit()
        response = client.delete(f"/api/conversations/{conv.id}", headers=auth_headers)
        assert response.get_json()["status"] == "deleted"
        assert test_database.list_trashed_conversations_paginated(test_user.id)[3] == 0

    def test_routes_require_auth(self, client: FlaskClient, test_conversation: Conversation) -> None:
        assert client.get("/api/conversations/trash").status_code == 401
        assert client.post(f"/api/conversations/{test_conversation.id}/restore").status_code == 401
        assert client.delete(f"/api/conversations/{test_conversation.id}/permanent").status_code == 401
        assert client.delete("/api/conversations/trash").status_code == 401
```

Also add this check to `TestDeleteConversation::test_deletes_conversation` in `test_routes_conversations.py`: `assert response.get_json()["status"] == "trashed"`.

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/pytest tests/integration/test_routes_conversation_trash.py -v`
Expected: FAIL (the trash routes 404 or 405, and delete returns `"deleted"`).

- [ ] **Step 3: Implement**

Schemas (`src/api/schemas/conversations.py`). Add to `ConversationResponse`:

```python
    deleted_at: str | None = None  # Set for conversations in the trash
    purge_at: str | None = None  # When a trashed conversation is deleted for good
```

and add:

```python
class EmptyTrashResponse(BaseModel):
    """Result of emptying the trash."""

    deleted: int = Field(..., description="Number of conversations permanently deleted")
```

Change `delete_conversation` in `conversations.py` to:

```python
@api.route("/conversations/<conv_id>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
def delete_conversation(user: User, conv_id: str) -> tuple[dict[str, str], int]:
    """Move a conversation to the trash.

    Agent and program conversations (planner, sports, language) have no
    trash view and are deleted immediately, as before.
    """
    conv = db.get_conversation(conv_id, user.id)
    if conv and (conv.is_agent or conv.is_planning or conv.is_sports or conv.is_language):
        db.delete_conversation(conv_id, user.id)
        logger.info("Conversation deleted", extra={"user_id": user.id, "conversation_id": conv_id})
        return {"status": "deleted"}, 200

    if not db.trash_conversation(conv_id, user.id):
        logger.warning(
            "Conversation not found for deletion",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")

    logger.info("Conversation trashed", extra={"user_id": user.id, "conversation_id": conv_id})
    return {"status": "trashed"}, 200
```

(`get_conversation` returns None for an already-trashed chat. `trash_conversation` then handles the retry idempotently.)

`src/api/routes/conversation_trash.py`:

```python
"""Conversation trash routes: list, restore, permanent delete, empty.

Attached to conversations.api (one shared "Conversations" blueprint keeps a
single OpenAPI tag). DELETE /conversations/<id> itself (move to trash) lives
in conversations.py.
"""

from datetime import timedelta
from typing import Any

from flask import request

from src.api.errors import raise_not_found_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.routes.conversations import api
from src.api.schemas.common import StatusResponse
from src.api.schemas.conversations import (
    ConversationsListPaginatedResponse,
    EmptyTrashResponse,
)
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _page_limit() -> int:
    limit_param = request.args.get("limit")
    if not limit_param:
        return Config.CONVERSATIONS_DEFAULT_PAGE_SIZE
    try:
        return max(1, min(int(limit_param), Config.CONVERSATIONS_MAX_PAGE_SIZE))
    except ValueError:
        return Config.CONVERSATIONS_DEFAULT_PAGE_SIZE


@api.route("/conversations/trash", methods=["GET"])
@api.output(ConversationsListPaginatedResponse)
@api.doc(responses=[429])
@rate_limit_conversations
@require_auth
def list_trashed_conversations(user: User) -> dict[str, Any]:
    """List conversations in the trash, most recently deleted first."""
    rows, next_cursor, has_more, total_count = db.list_trashed_conversations_paginated(
        user.id, limit=_page_limit(), cursor=request.args.get("cursor")
    )
    retention = timedelta(days=Config.TRASH_RETENTION_DAYS)
    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "model": c.model,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
                "message_count": message_count,
                "archived": c.archived,
                "last_message_preview": preview,
                "deleted_at": c.deleted_at.isoformat() if c.deleted_at else None,
                "purge_at": (c.deleted_at + retention).isoformat() if c.deleted_at else None,
            }
            for c, message_count, preview in rows
        ],
        "pagination": {
            "next_cursor": next_cursor,
            "has_more": has_more,
            "total_count": total_count,
        },
    }


@api.route("/conversations/trash", methods=["DELETE"])
@api.output(EmptyTrashResponse)
@api.doc(responses=[429])
@rate_limit_conversations
@require_auth
def empty_trash(user: User) -> dict[str, int]:
    """Permanently delete every conversation in the trash."""
    deleted = db.empty_trash(user.id)
    logger.info("Trash emptied", extra={"user_id": user.id, "deleted": deleted})
    return {"deleted": deleted}


@api.route("/conversations/<conv_id>/restore", methods=["POST"])
@api.output(StatusResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
def restore_conversation(user: User, conv_id: str) -> tuple[dict[str, str], int]:
    """Restore a conversation from the trash (back to the list or archive it was in)."""
    if not db.restore_conversation(conv_id, user.id):
        raise_not_found_error("Conversation")
    logger.info("Conversation restored", extra={"user_id": user.id, "conversation_id": conv_id})
    return {"status": "restored"}, 200


@api.route("/conversations/<conv_id>/permanent", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
def delete_conversation_permanently(user: User, conv_id: str) -> tuple[dict[str, str], int]:
    """Permanently delete a conversation that is in the trash."""
    if not db.delete_trashed_conversation(conv_id, user.id):
        raise_not_found_error("Conversation")
    logger.info(
        "Conversation permanently deleted",
        extra={"user_id": user.id, "conversation_id": conv_id},
    )
    return {"status": "deleted"}, 200
```

Route order: `/conversations/trash` is a static path, so Werkzeug ranks it above `/conversations/<conv_id>`. Still, check that `GET /conversations/trash` isn't swallowed by `GET /conversations/<conv_id>` (the test covers this).

Register the module in `src/api/routes/__init__.py` the same way `conversation_organize` is registered, and add a docstring line: `- conversation_trash.py: Trash list, restore, permanent delete, empty (4 routes, on conversations.api)`.

Then run `make openapi && make types`.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/integration/test_routes_conversation_trash.py tests/integration/test_routes_conversations.py tests/integration/test_openapi.py tests/integration/test_routes_sync.py -v`
Expected: PASS

### Task 5: Purge in the daily cleanup sweep

**Files:**
- Modify: `src/utils/file_retention.py` (`cleanup_expired_files`, module docstring), `scripts/cleanup_files.py` (docstring and log extra)
- Test: `tests/unit/test_file_retention.py`

**Interfaces:**
- Consumes: `purge_trashed_conversations(retention_days) -> int`, `Config.TRASH_RETENTION_DAYS`.
- Produces: `cleanup_expired_files()` result dict gains the key `"conversations_purged"`.

- [ ] **Step 1: Write the failing test** (append to `test_file_retention.py`, using its `seeded_env` / `test_database` fixtures)

```python
class TestTrashPurge:
    def test_sweep_purges_expired_trash(self, test_database, test_blob_store) -> None:
        user = test_database.get_or_create_user("trash@example.com", "Trash")
        conv = test_database.create_conversation(user.id, "Old trash")
        test_database.trash_conversation(conv.id, user.id)
        with test_database._pool.get_connection() as conn:
            conn.execute(
                "UPDATE conversations SET deleted_at = ? WHERE id = ?",
                ((datetime.now() - timedelta(days=15)).isoformat(), conv.id),
            )
            conn.commit()

        counts = cleanup_expired_files()

        assert counts["conversations_purged"] == 1
        assert test_database.list_trashed_conversations_paginated(user.id)[3] == 0
```

Check how `seeded_env` points `models.db` at `test_database` (the sweep reads `models.db`) and reuse that patching. If it's needed, take the `seeded_env` fixture instead of the two raw fixtures.

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/unit/test_file_retention.py -k Trash -v`
Expected: FAIL with `KeyError: 'conversations_purged'`

- [ ] **Step 3: Implement**

In `cleanup_expired_files`, just before the `if any(counts.values())` log:

```python
    # Trashed conversations past their retention window go for good
    counts["conversations_purged"] = models.db.purge_trashed_conversations(
        Config.TRASH_RETENTION_DAYS
    )
```

Change the docstring first line to "Delete expired attachment blobs, Gemini URI cache entries, and expired trash." In the module docstring, add one sentence: "The same sweep purges conversations trashed more than TRASH_RETENTION_DAYS ago." In `scripts/cleanup_files.py`, add `"conversations_purged": counts["conversations_purged"]` to the log `extra` and mention the trash purge in its docstring.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/unit/test_file_retention.py -v`
Expected: PASS

- [ ] **Step 5: Backend commit**

```bash
git switch -c feat/conversation-trash   # once, before the first commit
make lint > /tmp/.../lint.log 2>&1; echo "lint exit $?"
make test-all > /tmp/.../test-all.log 2>&1; echo "test-all exit $?"
# both must print exit 0; use the session scratchpad for the logs
git add migrations/0056_add_conversation_trash.py src/ scripts/cleanup_files.py .env.example \
  static/openapi.json web/src/types/generated-api.ts tests/
git commit -m "feat(conversations): move deleted conversations to a trash"
```

### Task 6: Frontend API client, types, store slice

**Files:**
- Modify: `web/src/types/api.ts` (Conversation), `web/src/api/conversations.ts`, `web/src/state/store.ts` (compose the slice, add it to the logout reset next to `initialArchiveData`), `web/src/config.ts`
- Create: `web/src/state/slices/trash.ts`
- Test: `web/tests/unit/store.test.ts` (new `describe('Store - Trash')`; add the trash fields to the initial-state fixture at the top, near line 32), `web/tests/unit/api-client.test.ts`

**Interfaces:**
- Produces:
  - `Conversation.deleted_at?: string | null; purge_at?: string | null`
  - `conversations.listTrash(limit?, cursor?) => Promise<{conversations, pagination}>`, `conversations.restore(id)`, `conversations.deletePermanently(id)`, `conversations.emptyTrash() => Promise<number>`
  - Store: `trashedConversations: Conversation[]`, `trashPagination: ConversationsPaginationState`, `isTrashView: boolean`, `setTrashedConversations`, `appendTrashedConversations`, `addTrashedConversation`, `removeTrashedConversation`, `clearTrash`, `setIsTrashView`, `setLoadingMoreTrash`, `initialTrashData()`
  - `TRASH_RETENTION_DAYS = 14` in `web/src/config.ts`

- [ ] **Step 1: Write the failing tests**

`store.test.ts`:

```ts
describe('Store - Trash', () => {
  beforeEach(() => useStore.setState(initialTrashData()));

  it('adds and removes trashed conversations, keeping the count', () => {
    const store = useStore.getState();
    store.setTrashedConversations([createConversation('1', 'One')], createPagination(false, 1));
    store.addTrashedConversation(createConversation('2', 'Two'));
    expect(useStore.getState().trashPagination.totalCount).toBe(2);
    useStore.getState().removeTrashedConversation('1');
    expect(useStore.getState().trashedConversations.map((c) => c.id)).toEqual(['2']);
    expect(useStore.getState().trashPagination.totalCount).toBe(1);
  });

  it('clearTrash empties list and count', () => {
    useStore.getState().setTrashedConversations([createConversation('1', 'One')], createPagination(false, 1));
    useStore.getState().clearTrash();
    expect(useStore.getState().trashedConversations).toEqual([]);
    expect(useStore.getState().trashPagination.totalCount).toBe(0);
  });
});
```

`api-client.test.ts`, inside `describe('conversations')`, following the existing `delete` test's fetch-mock style:

```ts
    describe('trash', () => {
      it('restore POSTs to /restore', async () => {
        mockFetch.mockResolvedValueOnce(jsonResponse({ status: 'restored' }));
        await conversations.restore('c1');
        expect(mockFetch).toHaveBeenCalledWith('/api/conversations/c1/restore', expect.objectContaining({ method: 'POST' }));
      });

      it('deletePermanently DELETEs /permanent', async () => {
        mockFetch.mockResolvedValueOnce(jsonResponse({ status: 'deleted' }));
        await conversations.deletePermanently('c1');
        expect(mockFetch).toHaveBeenCalledWith('/api/conversations/c1/permanent', expect.objectContaining({ method: 'DELETE' }));
      });

      it('emptyTrash returns the deleted count', async () => {
        mockFetch.mockResolvedValueOnce(jsonResponse({ deleted: 3 }));
        expect(await conversations.emptyTrash()).toBe(3);
      });
    });
```

Use whatever fetch-mock helper names the file already uses (`mockFetch` and `jsonResponse` above are placeholders for them).

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd web && npx vitest run tests/unit/store.test.ts tests/unit/api-client.test.ts`
Expected: FAIL (functions not defined)

- [ ] **Step 3: Implement**

`types/api.ts` Conversation, after `pinned`:

```ts
  // Trash state (only set on conversations from the trash listing)
  deleted_at?: string | null; // When it was moved to the trash
  purge_at?: string | null; // When the server deletes it for good
```

`web/src/config.ts`:

```ts
/** Days a deleted conversation stays restorable (mirrors the server's TRASH_RETENTION_DAYS default; the trash view shows the server's purge_at) */
export const TRASH_RETENTION_DAYS = 14;
```

`api/conversations.ts`, after `unarchive`:

```ts
  async restore(id: string): Promise<void> {
    // Idempotent server-side (restoring a live conversation is a no-op), safe to retry
    await request<{ status: string }>(`/api/conversations/${id}/restore`, {
      method: 'POST',
      retry: true,
    });
  },

  async deletePermanently(id: string): Promise<void> {
    // Not retried: a retry after a lost response would 404
    await request<{ status: string }>(`/api/conversations/${id}/permanent`, {
      method: 'DELETE',
    });
  },

  async emptyTrash(): Promise<number> {
    const data = await request<{ deleted: number }>('/api/conversations/trash', {
      method: 'DELETE',
    });
    return data.deleted;
  },
```

and after `listArchived` add `listTrash`, the same body but pointed at `/api/conversations/trash`. Update the module docstring to mention trash. Change the comment on `delete` to: "Moves to the trash; idempotent server-side, safe to retry".

`state/slices/trash.ts`: copy `archive.ts` with these renames: `archivedConversations→trashedConversations`, `archivedPagination→trashPagination`, `isArchiveView→isTrashView`, `ArchiveData/ArchiveSlice→TrashData/TrashSlice`, `initialArchiveData→initialTrashData`, `createArchiveSlice→createTrashSlice`; setters `setTrashedConversations`, `appendTrashedConversations`, `addTrashedConversation`, `removeTrashedConversation`, `setIsTrashView`, `setLoadingMoreTrash`. Drop `updateArchivedConversation` (trashed rows aren't editable) and add:

```ts
  clearTrash: () => set({ trashedConversations: [], trashPagination: emptyConversationsPagination() }),
```

Compose it in `store.ts` the same way `createArchiveSlice` is composed, and spread `initialTrashData()` wherever `initialArchiveData()` is spread (logout reset).

- [ ] **Step 4: Run the tests and typecheck**

Run: `cd web && npx vitest run tests/unit/store.test.ts tests/unit/api-client.test.ts && npx tsc --noEmit`
Expected: PASS, no type errors (fix any test mocks of the store state that tsc flags, per the "update ALL test mocks" pitfall).

### Task 7: Trash view, delete dialog, menu entry, routing

**Files:**
- Create:
  - `web/src/core/trash.ts`: actions and view navigation, mirroring `core/archive.ts`.
  - `web/src/components/TrashView.ts`: rendering, kept out of `Sidebar.ts`, which is already 997 lines.
  - `web/src/styles/components/trash.css`: only if the archive classes can't be reused. Use component-prefixed `trash-*` names.
- Modify:
  - `web/src/core/conversation-actions.ts` (`deleteConversation`)
  - `web/src/components/Sidebar.ts`: the `renderConversationsList` branch, the user menu item, and an entry badge call in `renderUserInfo`.
  - `web/src/core/events.ts`: click delegation.
  - `web/src/router/deeplink.ts`: `'trash'` route, `setTrashHash`, `isTrash` on the callback and on `InitialRoute`.
  - `web/src/core/conversation-deeplink.ts`: `isTrash` view handling and leave.
  - `web/src/core/init.ts`: initial route, the auth:login route, and a background count load.
  - `web/src/utils/icons.ts`: a `TRASH_ICON` / `RESTORE_ICON`, if one doesn't already exist. Check first, since `DELETE_ICON` and `UNARCHIVE_ICON` exist and might be reused.
- Test: `web/tests/component/TrashView.test.ts` (new), plus updates to every `InitialRoute` literal in the tests (`grep -rn "isArchive" web/tests`).

**Interfaces:**
- Consumes: Task 6 API, store and constant.
- Produces:
  - `trash.ts` exports: `moveToTrashUndo`, `restoreConversation(convId)`, `deleteConversationForever(convId)`, `emptyTrash()`, `navigateToTrash()`, `leaveTrashView()`, `loadTrashedConversations()`.
  - `TrashView.ts` exports: `renderTrashView(container: HTMLDivElement): void`, `renderTrashEntry(): void`, `cleanupTrashInfiniteScroll(): void`, `daysLeftLabel(purgeAt: string, now?: Date): string`.
  - DOM hooks: `.user-menu-trash` (menu item, `.trash-count` badge), `.trash-view-header`, `[data-trash-back]`, `[data-restore-id]`, `[data-delete-forever-id]`, `[data-empty-trash]`, `.trash-days-left`.

- [ ] **Step 1: Write the failing component tests**

`web/tests/component/TrashView.test.ts` (follow `Sidebar.test.ts` for DOM and store setup):

```ts
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../../src/state/store';
import { renderTrashView, daysLeftLabel } from '../../src/components/TrashView';

describe('daysLeftLabel', () => {
  const now = new Date('2026-10-01T12:00:00');
  it('rounds up partial days', () => {
    expect(daysLeftLabel('2026-10-03T08:00:00', now)).toBe('2 days left');
  });
  it('says 1 day left', () => {
    expect(daysLeftLabel('2026-10-02T06:00:00', now)).toBe('1 day left');
  });
  it('never goes negative', () => {
    expect(daysLeftLabel('2026-09-30T00:00:00', now)).toBe('Deleting soon');
  });
});

describe('renderTrashView', () => {
  let container: HTMLDivElement;
  beforeEach(() => {
    container = document.createElement('div');
    useStore.setState({
      trashedConversations: [
        { id: 'c1', title: 'Gone <b>', model: 'm', created_at: '', updated_at: '', purge_at: '2026-10-10T00:00:00' },
      ],
      trashPagination: { nextCursor: null, hasMore: false, totalCount: 1, isLoadingMore: false },
    });
  });

  it('renders rows with restore and delete-forever actions, escaped titles', () => {
    renderTrashView(container);
    expect(container.querySelector('.trash-view-header')).not.toBeNull();
    expect(container.querySelector('[data-restore-id="c1"]')).not.toBeNull();
    expect(container.querySelector('[data-delete-forever-id="c1"]')).not.toBeNull();
    expect(container.querySelector('[data-empty-trash]')).not.toBeNull();
    expect(container.innerHTML).toContain('Gone &lt;b&gt;');
    expect(container.querySelector('.trash-days-left')).not.toBeNull();
  });

  it('shows an empty state without the empty-trash action', () => {
    useStore.setState({ trashedConversations: [], trashPagination: { nextCursor: null, hasMore: false, totalCount: 0, isLoadingMore: false } });
    renderTrashView(container);
    expect(container.textContent).toContain('Trash is empty');
    expect(container.querySelector('[data-empty-trash]')).toBeNull();
  });
});
```

Match the `ConversationsPaginationState` field names in `conversationOrder.ts`.

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd web && npx vitest run tests/component/TrashView.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `components/TrashView.ts`**

Mirror `renderArchiveView` / `renderArchiveEntry` / `setupArchiveInfiniteScroll` from `Sidebar.ts` (lines ~724–860). Differences:
- Header: back button `data-trash-back`, title "Trash", count, and, when the list is non-empty, a text button `<button class="trash-empty-btn" data-empty-trash>Empty</button>`. Use `archive-view-header` styling plus a `trash-view-header` class.
- Empty state text: `Trash is empty`. Under it, a muted line: `Deleted conversations stay here for ${TRASH_RETENTION_DAYS} days.`
- Row: no `role="button"` click-through (rows don't open the chat). It shows the title, `<span class="trash-days-left">${daysLeftLabel(conv.purge_at)}</span>`, and the desktop actions `[data-restore-id]` (`UNARCHIVE_ICON`, aria-label "Restore") and `[data-delete-forever-id]` (`DELETE_ICON`, aria-label "Delete forever"). Swipe actions on mobile use the same two buttons, matching `renderArchivedConversationItem`.
- Infinite scroll calls `conversations.listTrash(…, cursor)` → `appendTrashedConversations`.
- `renderTrashEntry()` toggles `.user-menu-trash` hidden when the count is 0 and sets `.trash-count`.

```ts
export function daysLeftLabel(purgeAt: string | null | undefined, now: Date = new Date()): string {
  if (!purgeAt) return '';
  const days = Math.ceil((new Date(purgeAt).getTime() - now.getTime()) / MS_PER_DAY);
  if (days <= 0) return 'Deleting soon';
  return days === 1 ? '1 day left' : `${days} days left`;
}
```

(Use the existing `MS_PER_DAY` constant if there is one. Otherwise add one beside `MS_PER_MINUTE` in `constants.ts`.)

- [ ] **Step 4: Implement `core/trash.ts`** (mirror `core/archive.ts`)

```ts
/**
 * Conversation trash: undo after delete, restore, delete forever, empty, and the trash view.
 */

/** Undo for the "Moved to trash" toast: restore and put the row back. */
export async function restoreConversation(convId: string, conv?: Conversation): Promise<void> {
  const store = useStore.getState();
  const source = conv ?? store.trashedConversations.find((c) => c.id === convId);
  if (!source) return;
  try {
    await conversations.restore(convId);
    store.removeTrashedConversation(convId);
    const restored = { ...source, deleted_at: null, purge_at: null };
    if (restored.archived) {
      store.addArchivedConversation(restored);
    } else {
      store.addConversation(restored);
    }
    renderConversationsList();
    toast.success('Conversation restored.');
  } catch (error) {
    log.error('Failed to restore conversation', { error, conversationId: convId });
    toast.error('Failed to restore conversation.');
  }
}

export async function deleteConversationForever(convId: string): Promise<void> {
  const confirmed = await showConfirm({
    title: 'Delete forever',
    message: 'Permanently delete this conversation? This cannot be undone.',
    confirmLabel: 'Delete forever',
    cancelLabel: 'Cancel',
    danger: true,
  });
  if (!confirmed) return;
  try {
    await conversations.deletePermanently(convId);
  } catch (error) {
    if (!isNotFoundError(error)) {
      log.error('Failed to delete conversation permanently', { error, conversationId: convId });
      toast.error('Failed to delete conversation.');
      return;
    }
    // 404: already purged - drop the stale row below
  }
  useStore.getState().removeTrashedConversation(convId);
  renderConversationsList();
}

export async function emptyTrash(): Promise<void> {
  const confirmed = await showConfirm({
    title: 'Empty trash',
    message: 'Permanently delete all conversations in the trash? This cannot be undone.',
    confirmLabel: 'Empty trash',
    cancelLabel: 'Cancel',
    danger: true,
  });
  if (!confirmed) return;
  try {
    await conversations.emptyTrash();
    useStore.getState().clearTrash();
    renderConversationsList();
  } catch (error) {
    log.error('Failed to empty trash', { error });
    toast.error('Failed to empty trash.');
  }
}
```

Use the error-classification helper the API layer already has for `isNotFoundError` (look for an `ApiError` with a `status` in `api/http.ts`). `navigateToTrash`, `leaveTrashView` and `loadTrashedConversations` are `navigateToArchive`, `leaveArchiveView` and `loadArchivedConversations` with the trash store and API substituted. `navigateToTrash` must also clear `isArchiveView` (and `navigateToArchive` must clear `isTrashView`), so the two views never stack.

- [ ] **Step 5: Change the delete flow in `conversation-actions.ts`**

```ts
export async function deleteConversation(convId: string): Promise<void> {
  const confirmed = await showConfirm({
    title: 'Move to trash',
    message: `Move this conversation to the trash? You can restore it for ${TRASH_RETENTION_DAYS} days.`,
    confirmLabel: 'Move to trash',
    cancelLabel: 'Cancel',
    danger: true,
  });

  if (!confirmed) return;

  // For temp conversations, just remove locally (no API call needed)
  if (isTempConversation(convId)) {
    removeConversationFromUI(convId);
    return;
  }

  // Archived rows are tracked by list membership (main-list rows carry no flag)
  const store = useStore.getState();
  const archivedConv = store.archivedConversations.find((c) => c.id === convId);
  const isArchived = archivedConv !== undefined;
  const found = archivedConv ?? store.conversations.find((c) => c.id === convId);
  const conv = found ? { ...found, archived: isArchived } : undefined;

  try {
    await conversations.delete(convId);

    if (isArchived) {
      store.removeArchivedConversation(convId);
      renderConversationsList();
    } else {
      removeConversationFromUI(convId);
    }
    if (conv) {
      store.addTrashedConversation({ ...conv, deleted_at: new Date().toISOString() });
    }
    toast.success('Moved to trash.', {
      action: { label: 'Undo', onClick: () => restoreConversation(convId, conv) },
    });
  } catch (error) {
    log.error('Failed to delete conversation', { error, conversationId: convId });
    toast.error('Failed to delete conversation. Please try again.');
  }
}
```

`purge_at` isn't known locally; the trash view reloads from the server when opened, so `navigateToTrash` always calls `loadTrashedConversations()` rather than lazy-loading only when the list is empty. Then `daysLeftLabel` always has server data.

- [ ] **Step 6: Wire the menu, events and routing**

- `Sidebar.ts::renderUserInfo`: after the archive item, add
  ```html
  <button class="user-menu-item user-menu-trash hidden" role="menuitem" data-route="trash">
    ${TRASH_ICON}<span>Trash</span><span class="trash-count">0</span>
  </button>
  ```
  and call `renderTrashEntry()` next to `renderArchiveEntry()`.
- `Sidebar.ts::renderConversationsList`: after the archive branch,
  ```ts
  if (useStore.getState().isTrashView) {
    lastRenderedListHtml = '';
    renderTrashView(container);
    return;
  }
  ```
- `events.ts`: next to `.user-menu-archive`, handle `.user-menu-trash` → `navigateToTrash()`. Next to the unarchive handlers, handle `[data-restore-id]` → `restoreConversation(id)`, `[data-delete-forever-id]` → `deleteConversationForever(id)`, `[data-empty-trash]` → `emptyTrash()`, and `[data-trash-back]` → `leaveTrashView()`. Each one calls `e.stopPropagation()` the way the archive handlers do.
- `deeplink.ts`: add `'trash'` to `RouteType`, `if (cleanHash === '/trash') return { type: 'trash' };`, and `setTrashHash()` (a copy of `setArchiveHash` with `'#/trash'`). Append an 8th positional `isTrash` to `HashChangeCallback` and to every `hashChangeCallback(...)` call (`false` everywhere, `true` for the trash route). Add `isTrash: boolean` to `InitialRoute` and to every literal that returns it, plus a trash branch.
- `conversation-deeplink.ts`: `isTrash` in `DeepLinkViews`, `navigateToViewFromHash` (`else if (views.isTrash) navigateToTrash();`), `leaveViewsForHashNavigation` (`if (store.isTrashView) leaveTrashView();`), and the `handleDeepLinkNavigation` signature and pass-through.
- `init.ts`: `else if (initialRoute?.isTrash) { navigateToTrash(); }`, `isTrash: route.type === 'trash'` in the auth:login literal, and a background `loadTrashedConversations().catch(() => {})` next to the archive one, so the menu badge shows.
- Every test that builds an `InitialRoute` or calls the hash callback with seven args gets the extra field or argument (`grep -rn "isArchive" web/tests web/src`).

- [ ] **Step 7: Run the frontend checks**

Run: `cd web && npx vitest run && npx tsc --noEmit && npx eslint src tests`
Expected: PASS, 0 errors

### Task 8: E2E (desktop and mobile)

**Files:**
- Modify: `web/tests/e2e/conversation.spec.ts` (`Conversation deletion` describe), `web/tests/e2e/deeplink.spec.ts`, `web/tests/e2e/mobile.spec.ts`

- [ ] **Step 1: Write the E2E tests**

In the `Conversation deletion` describe (the beforeEach already creates one conversation), add:

```ts
  test('delete moves to trash and Undo restores', async ({ page }) => {
    const convItem = page.locator('.conversation-item-wrapper').first();
    await convItem.hover();
    await convItem.locator('.conversation-delete').click();
    const modal = page.locator('.modal-container:not(.modal-hidden)');
    await expect(modal).toContainText('Move this conversation to the trash');
    await modal.locator('.modal-confirm').click();

    await expect(page.locator('.conversation-item-wrapper')).toHaveCount(0);
    await page.locator('.toast').getByRole('button', { name: 'Undo' }).click();
    await expect(page.locator('.conversation-item-wrapper')).toHaveCount(1);
  });

  test('trash view restores, deletes forever, and empties', async ({ page }) => {
    const deleteFirst = async () => {
      const item = page.locator('.conversation-item-wrapper').first();
      await item.hover();
      await item.locator('.conversation-delete').click();
      await page.locator('.modal-container:not(.modal-hidden) .modal-confirm').click();
    };
    await deleteFirst();

    await page.goto('/#/trash');
    await expect(page.locator('.trash-view-header')).toBeVisible({ timeout: 20000 });
    const row = page.locator('.conversation-item-wrapper').first();
    await expect(row.locator('.trash-days-left')).toContainText('days left');

    await row.hover();
    await row.locator('[data-restore-id]').click();
    await expect(page.locator('.conversations-empty')).toContainText('Trash is empty');

    await page.locator('[data-trash-back]').click();
    await deleteFirst();
    await page.goto('/#/trash');
    await page.locator('[data-empty-trash]').click();
    await page.locator('.modal-container:not(.modal-hidden) .modal-confirm').click();
    await expect(page.locator('.conversations-empty')).toContainText('Trash is empty');
  });
```

Keep the existing `clicking delete removes conversation` and `can cancel deletion` tests. They still describe correct behavior.

In `deeplink.spec.ts`, beside the `#/archive` test:

```ts
  test('#/trash opens the trash view directly', async ({ page }) => {
    await page.goto('/#/trash');
    await expect(page.locator('.trash-view-header')).toBeVisible({ timeout: 20000 });
  });
```

In `mobile.spec.ts`, add one test that deletes via the swipe/action-sheet path the file already uses for delete or archive, opens `#/trash`, and restores via the `[data-restore-id]` swipe button. Model it on the closest existing mobile archive or delete test in that file.

- [ ] **Step 2: Build and run the specs**

Run: `make build && cd web && npx playwright test tests/e2e/conversation.spec.ts tests/e2e/deeplink.spec.ts tests/e2e/mobile.spec.ts`
Expected: PASS. If it fails, use the `e2e-debugger` agent and don't add retries.

- [ ] **Step 3: Check it by hand in the browser**

Start `make dev`, delete a chat, check the toast's Undo, open Trash from the user menu, restore one chat and delete another forever. Do this at desktop width and at 375px. Check the trash view styling in light and dark mode.

### Task 9: Docs, spec sync, final verification, commit

**Files:**
- Modify:
  - `docs/features/ui-features.md`: a Trash section covering the behavior, the 14-day retention, `TRASH_RETENTION_DAYS`, the purge in the daily cleanup sweep, and that agent and program chats are hard-deleted.
  - `docs/superpowers/specs/2026-10-01-conversation-trash-design.md`: idempotent trash and restore, and the `delete_trashed_conversation` name.
  - `TODO.md`: remove a matching entry if there is one.

- [ ] **Step 1:** Run the `docs-updater` agent with a summary of Tasks 1–8. Review its diff: no hostnames or infra details.
- [ ] **Step 2:** Run `superpowers:requesting-code-review` on the branch and fix what's confirmed.
- [ ] **Step 3:** `make lint` and `make test-all`, each logged to the scratchpad and judged by exit code (both 0).
- [ ] **Step 4: Commit**

```bash
git add web/ docs/ TODO.md
git commit -m "feat(web): trash view with restore, delete forever, and empty trash"
```

- [ ] **Step 5:** Ask the user before merging to main or deploying. The production deploy applies migration 0056, so deploy once and don't deploy twice in quick succession.
