# Conversations

Renaming, deleting and restoring conversations in the sidebar. Part of
[UI Features](ui-features.md).

## Conversation Management

The sidebar displays a list of conversations with hover actions for rename and delete.

### Rename

- **Desktop**: Hover over a conversation to reveal action buttons, click the pencil icon to rename
- **Mobile**: Swipe left on a conversation to reveal rename and delete buttons
- Opens a prompt modal with the current title pre-filled
- Updates both the sidebar title and the chat header title (if viewing that conversation)
- Shows a success toast on completion
- Empty names are rejected (modal closes without changes)

### Delete

- **Desktop**: Hover over a conversation to reveal action buttons, click the trash icon to delete
- **Mobile**: Swipe left on a conversation to reveal delete button
- Deleting moves the conversation to the [trash](#trash): the confirm modal reads "Move this
  conversation to the trash? You can restore it for 14 days.", and a "Moved to trash." toast offers **Undo**
- Cost data is intentionally preserved after deletion for accurate reporting

### Bulk delete

Clearing out many chats at once, without a confirm per chat (they stay restorable in the
[trash](#trash)).

- **Entering**: user menu → **Select chats**. The sidebar header and footer give way to a
  selection bar (**Cancel** · "N selected" · **Select all**) and a **Move N to trash** button;
  the nav entries, search box, hover actions and swipe are hidden while selecting.
- **Picking**: tapping or clicking a row ticks it instead of opening it.
- **Select all** selects every unpinned chat in the main list, including pages not loaded yet,
  resolved server-side. Unticking a row excludes it; a pinned chat counts only when ticked by
  hand. The count is the list's `total_count` minus loaded pinned chats (all pinned chats load
  up front), minus exclusions. Chats created after **Select all** was pressed (on another
  device) are never swept up: the request carries `created_before`.
- **Deleting**: no confirm. The button reads "Moving…" while the one request runs; once the
  server confirms, the rows leave, selection mode closes, and a "Moved N chats to trash." toast
  offers one **Undo** for the batch (restored in chunks of `CONVERSATIONS_BULK_MAX_IDS`; chats
  from unloaded pages come back through sync). On failure nothing is removed and the selection
  stays for a retry.
- **Exiting**: Cancel, Escape, or a completed delete.
- Code: selection state in [selection.ts](../../web/src/state/slices/selection.ts), UI in
  [SidebarSelection.ts](../../web/src/components/SidebarSelection.ts), actions
  `bulkDeleteConversations` ([conversation-actions.ts](../../web/src/core/conversation-actions.ts))
  and `restoreConversations` ([core/trash.ts](../../web/src/core/trash.ts)).

### Trash

Regular chats are soft-deleted: `DELETE /api/conversations/<id>` sets `conversations.deleted_at`
([migration 0056](../../migrations/0056_add_conversation_trash.py)) and returns `{"status": "trashed"}`.
The conversation stays restorable for `TRASH_RETENTION_DAYS` (default 14), then is purged for good.

**Bypasses the trash**: agent, planner, sports and language conversations are still hard-deleted
(`{"status": "deleted"}`); they are owned by their feature, not the chat list.

**Hidden everywhere**: every user-facing query filters `deleted_at IS NULL` - the list, pinned and archived
lists, `get_conversation`, rename/archive/pin, [sync](sync.md#delete-detection),
[full-text search](search.md) and semantic recall (`get_message_rows_for_ids`). The search index is left
alone on trash/restore (search filters at query time), so restore needs no reindex.

**Database** - `ConversationTrashMixin` in [conversation_trash.py](../../src/db/models/conversation_trash.py):

| Method | Behavior |
|--------|----------|
| `trash_conversation()` | Idempotent; a retried delete keeps the original `deleted_at` |
| `restore_conversation()` | Idempotent; `archived`/`pinned` untouched, so an archived chat returns to the archive |
| `list_trashed_conversations_paginated()` | Most recently deleted first, cursor-paginated |
| `delete_trashed_conversation()` / `empty_trash()` | Permanent delete of one / all trashed rows (rows, then blobs); `empty_trash` and the purge delete in chunks of 25 per transaction (one commit per chat, plus full search-index scans before [migration 0067](search.md#trigger-based-sync), made a 1000-chat trash take minutes; now ~6 s) |
| `purge_trashed_conversations(retention_days)` | Deletes rows trashed longer ago than the retention window |
| `trash_conversations()` / `trash_all_conversations()` / `restore_conversations()` | [Bulk delete](#bulk-delete): one `BEGIN IMMEDIATE` transaction each, return the ids changed; only regular chats (not agent / planner / sports / language) |

**API** - [conversation_trash.py](../../src/api/routes/conversation_trash.py), on the shared `Conversations` blueprint:

| Route | Purpose |
|-------|---------|
| `GET /api/conversations/trash` | Paginated list; items carry `deleted_at` and a server-computed `purge_at` |
| `POST /api/conversations/<id>/restore` | Restore (404 if not in the trash) |
| `DELETE /api/conversations/<id>/permanent` | Delete one trashed conversation forever |
| `DELETE /api/conversations/trash` | Empty the trash; returns `{"deleted": n}` |
| `POST /api/conversations/bulk-trash` | Bulk delete: `{"ids": [...]}`, or `{"all": true, "exclude_ids": [...], "ids": [...], "created_before": ts}`; returns `{"trashed_ids": [...]}` |
| `POST /api/conversations/bulk-restore` | Undo of a bulk delete: `{"ids": [...]}`; returns `{"restored_ids": [...]}` |

**Purge**: the daily file-cleanup sweep (`cleanup_expired_files()` in
[file_retention.py](../../src/utils/file_retention.py)) also calls `purge_trashed_conversations()`, reported
as `conversations_purged`. It runs on a timer in production and via the dev scheduler locally - see
[Scheduled Jobs](../architecture/scheduled-jobs.md).

```bash
TRASH_RETENTION_DAYS=14   # days a deleted conversation stays restorable
CONVERSATIONS_BULK_MAX_IDS=500   # most ids one bulk trash / restore request may carry
```

**Frontend**: the user menu has a **Trash** entry with a count (hidden while the trash is empty); it opens a sidebar full-view like the archive
(`#/trash` deep link) with per-row Restore / Delete forever, "N days left" labels, and Empty trash
(disabled, reading "Emptying…", while the request runs - repeated taps used to start a purge each).
State lives in the trash slice ([trash.ts](../../web/src/state/slices/trash.ts)), actions in
[core/trash.ts](../../web/src/core/trash.ts), rendering in [TrashView.ts](../../web/src/components/TrashView.ts).

Pitfalls:

- **Trash rows carry `data-trash-id`, not `data-conv-id`**, so the sidebar's click delegation can't open them.
- **Menu badges refresh before the early returns**: `renderConversationsList()` calls `renderArchiveEntry()` /
  `renderTrashEntry()` before its empty/loading early returns. They used to run at the end, so a render that
  hit an early return (e.g. deleting the last chat) left a stale count.
- **Locally trashed rows have an estimated `purge_at`** (now + the frontend `TRASH_RETENTION_DAYS` in
  [config.ts](../../web/src/config.ts)); `navigateToTrash()` always reloads to get the server's value.
- **Web and server retention are separate settings**: the confirm-dialog text uses the frontend constant,
  so change both if you change `TRASH_RETENTION_DAYS`.

### Key Files

- [Sidebar.ts](../../web/src/components/Sidebar.ts) - Conversation list rendering, rename/delete handlers
- [conversation-actions.ts](../../web/src/core/conversation-actions.ts) - `renameConversation()`, `deleteConversation()` (trash + Undo)
- [core/trash.ts](../../web/src/core/trash.ts), [TrashView.ts](../../web/src/components/TrashView.ts) - Trash actions and view
- [Modal.ts](../../web/src/components/Modal.ts) - `showPrompt()` and `showConfirm()` dialogs

### Testing

- Backend: [test_db_conversation_trash.py](../../tests/integration/test_db_conversation_trash.py),
  [test_routes_conversation_trash.py](../../tests/integration/test_routes_conversation_trash.py),
  purge in [test_file_retention.py](../../tests/unit/test_file_retention.py)
- Frontend: [trash-actions.test.ts](../../web/tests/unit/trash-actions.test.ts),
  [TrashView.test.ts](../../web/tests/component/TrashView.test.ts); E2E trash flows in
  [conversation.spec.ts](../../web/tests/e2e/conversation.spec.ts) and [mobile.spec.ts](../../web/tests/e2e/mobile.spec.ts)
