# Conversation Trash - Design

Status: approved design, Oct 1 2026.

## Problem

Deleting a conversation destroys it immediately (rows, then attachment blobs). Deletes
are sometimes regretted, and there is no way back.

## Goal and success criteria

Deleting a conversation moves it to a trash. It stays restorable for
`TRASH_RETENTION_DAYS` (default 14), then is permanently deleted.

- Delete keeps its confirmation dialog, reworded to say the conversation goes to the
  trash; afterwards a "Moved to trash" toast offers Undo.
- A trashed conversation disappears everywhere a live one shows up: sidebar list,
  pinned list, archive, single-conversation fetch, chat send/stream, full-text search,
  semantic recall, and sync (other devices drop it as they do a deleted one today).
- A Trash view (user menu entry with a count, `#trash` route) lists trashed
  conversations with the days left, Restore, Delete forever, and Empty trash.
- Restore returns the conversation where it was (main list or archive).
- The daily cleanup sweep hard-deletes conversations trashed more than
  `TRASH_RETENTION_DAYS` ago, including their attachment blobs.

Non-goals: trash for agent/program/planner conversations (they keep deleting
immediately); opening or reading a trashed conversation (restore it first); trash for
single messages.

## Design

### 1. Data

Migration `0056_add_conversation_trash`:

- `ALTER TABLE conversations ADD COLUMN deleted_at TEXT` (NULL = live).
- Index `idx_conversations_user_deleted ON conversations(user_id, deleted_at)`.

`deleted_at` is a naive local ISO timestamp, like `updated_at`. Trashing sets
`deleted_at` and bumps `updated_at` (so incremental sync sees the change); restoring
clears `deleted_at` and bumps `updated_at`. The `archived` and `pinned` columns are not
touched.

The FTS `search_index` is left as is: search filters trashed conversations at query time
(see 2), so restore needs no reindexing, and the purge's hard delete removes index rows
through the existing message/conversation paths.

`Conversation` dataclass gains `deleted_at: datetime | None = None`.

### 2. Backend

New mixin `ConversationTrashMixin` (`src/db/models/conversation_trash.py`), mirroring
`ConversationArchiveMixin`:

- `trash_conversation(conv_id, user_id) -> bool` - owned conversation; idempotent (a retried
  DELETE keeps the original `deleted_at`, so it neither 404s nor extends retention).
- `restore_conversation(conv_id, user_id) -> bool` - owned conversation; idempotent (no-op
  for a live one).
- `list_trashed_conversations_paginated(user_id, limit, cursor)` - ordered by
  `updated_at DESC, id DESC` (trashing bumps `updated_at`, so this is trash order and the
  shared cursor helpers apply), same summary tuple shape as the archive listing.
- `delete_trashed_conversation(conv_id, user_id) -> bool` - trashed conversations
  only; delegates to the existing hard `delete_conversation` (blob cleanup included).
- `empty_trash(user_id) -> int`.
- `purge_trashed_conversations(retention_days) -> int` - all users, `deleted_at` older
  than the cutoff, via the same hard delete.

The existing `delete_conversation` stays the hard delete (agents, programs, purge use
it). Every user-facing conversation query adds `deleted_at IS NULL`:
`conversation_listing.py` (lists, counts, sync), pinned and archived lists,
`get_conversation` (so send/stream/rename/archive/pin on a trashed id 404),
`search` (join on `c.deleted_at IS NULL`), and `get_message_rows_for_ids` (semantic
recall). Trash mixin methods query trashed rows directly.

Routes (on the conversations blueprint, in a new `conversation_trash.py`, rate-limited
and authed like `conversation_organize.py`):

| Route | Effect |
|---|---|
| `DELETE /conversations/<id>` | moves to trash (`trashed`); agent/program chats hard-delete (`deleted`); 404 if missing |
| `GET /conversations/trash` | paginated list; each item adds `deleted_at`, `purge_at` |
| `POST /conversations/<id>/restore` | restore; 404 if missing |
| `DELETE /conversations/<id>/permanent` | hard delete; 404 if not in trash |
| `DELETE /conversations/trash` | empty trash; returns the count deleted |

`purge_at = deleted_at + TRASH_RETENTION_DAYS`, computed server-side so the client never
needs the retention setting. Pydantic schemas in `src/api/schemas/`; OpenAPI and
TypeScript types regenerated (`make openapi`, `make types`).

Purge: `cleanup_expired_files()` (the daily sweep run by `scripts/cleanup_files.py` in
production and the dev scheduler locally) also calls
`purge_trashed_conversations(Config.TRASH_RETENTION_DAYS)` and reports the count. No new
timer or deploy step.

Config: `TRASH_RETENTION_DAYS: int = int(os.getenv("TRASH_RETENTION_DAYS", "14"))` in
`src/config.py` and `.env.example`.

### 3. Frontend

- `deleteConversation` (`web/src/core/conversation-actions.ts`): dialog title "Move to
  trash", message "Move this conversation to the trash? You can restore it for 14 days.",
  confirm label "Move to trash". Afterwards `toast.success('Moved to trash.')` with an
  Undo action that restores. The "14" comes from a frontend constant kept in step with
  the server default (the dialog is advisory; `purge_at` in the trash view is the truth).
  A locally trashed row gets an estimated `purge_at` so its label is never blank; opening
  the trash view always reloads the server's values.
- API client: `conversations.listTrash`, `restore`, `deletePermanently`, `emptyTrash`.
- Store: a `trash` slice mirroring `state/slices/archive.ts` (list, pagination, count,
  `isTrashView`).
- New `web/src/core/trash.ts` mirroring `core/archive.ts`: restore (re-inserts into the
  active or archived list per the `archived` flag), delete forever and empty trash (each
  with a confirm dialog: "This cannot be undone").
- Sidebar: "Trash" user-menu item with count beside Archive; the trash view renders rows
  with title, "N days left" (from `purge_at`), Restore and Delete forever (buttons on
  desktop, swipe actions on mobile, as the archive view does), and an "Empty trash"
  header action. Rows are not clickable into the chat.
- Routing: `#trash` deeplink beside `#archive`.
- Sync: no change - trashed conversations are absent from the server's lists, so the
  existing full-sync delete detection removes them on other devices.

### 4. Error handling

- Trash/restore/permanent/empty on a missing or foreign id: 404 (no information leak).
- Restore of an id purged meanwhile: 404; the client toasts the failure.
- Delete forever of an id purged meanwhile: 404 is treated as already gone; the row is removed.
- Purge failure is logged by the existing sweep's error handling and retried next run;
  the hard delete commits rows before blob cleanup, so a crash leaves only orphaned blobs.

## Testing

- Unit (`tests/unit/`): trash/restore state transitions and ownership; each filtered
  query excludes trashed rows (lists, counts, pinned, archived, get, sync, search,
  semantic recall); purge cutoff boundary; restore keeps `archived`/`pinned`;
  `purge_at` computation.
- Integration (`tests/integration/`): every route's success and 404 paths; DELETE then
  GET returns 404; trash listing pagination; empty trash count; cleanup sweep purges.
- Frontend unit/component: trash slice, trash view rendering and actions.
- E2E (`web/tests/e2e/`), desktop and mobile: delete (confirm) -> gone from sidebar ->
  Undo restores; delete -> Trash view -> Restore; Delete forever; Empty trash.
- Visual baselines for the new view if the visual suite covers the archive view.

## Docs

Update the conversation/UI page under `docs/features/` (trash behavior, retention env
var, purge in the daily sweep).
