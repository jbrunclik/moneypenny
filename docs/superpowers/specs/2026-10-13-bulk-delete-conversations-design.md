# Bulk Delete Conversations - Design

Status: approved design, Oct 13 2026.

## Problem

Clearing out many chats means deleting them one at a time, each behind a confirm
modal. Since the [trash](../../features/ui-features.md#trash) shipped, a delete is
reversible (restorable for `TRASH_RETENTION_DAYS`, plus an Undo toast), so the modal
is friction rather than protection, and doing it dozens of times is tedious. Looping
the single `DELETE /api/conversations/<id>` is not an option either: conversation
endpoints are limited to `RATE_LIMIT_CONVERSATIONS` (60 per minute).

## Goal and success criteria

A user can select many chats in the main sidebar list and move them to the trash in
one action, without a confirm, and undo it in one action.

- Hand-picked selection and "Select all" both work; "Select all" covers chats on pages
  not yet loaded and skips pinned chats unless ticked by hand.
- One request trashes the whole batch in one transaction - never half a batch.
- One Undo restores exactly the chats that batch trashed.
- A chat created on another device after "Select all" was pressed is never trashed.
- Other devices drop (and, on Undo, regain) the rows on their next sync tick.
- Works on desktop and mobile (below the 768px breakpoint).

## Scope

In: delete (move to trash) from the main conversation list.

Out (v1): bulk archive, selection in the archive view, selection in the trash (it
already has "Empty trash"), criteria-based selection ("older than X"), a long-press
entry point on mobile (it would compete with row swipe).

## UX

**Entering.** A "Select chats" entry in the user menu, next to Archive and Trash.

**Selection mode.**
- The sidebar header (brand + New Chat) is replaced by a selection bar:
  **Cancel** - "N selected" - **Select all** (reads **Deselect all** while in
  select-all mode).
- Each row shows a checkbox on the left; tapping or clicking a row toggles it instead
  of opening the chat. Hover actions and swipe gestures are disabled.
- The planner / agents / sports / language entries and the search box are hidden;
  only regular chats are selectable.
- **Select all** switches to select-all mode: every unpinned chat counts as selected,
  including unloaded pages. Unticking a row adds it to an exclusion set; ticking a
  pinned row by hand includes it.
- A sticky **Move N to trash** button replaces the sidebar footer; disabled at N = 0.

**Deleting.** No confirm modal. The selected rows disappear optimistically, selection
mode closes, and a toast reads "Moved 23 chats to trash." with **Undo**. If the open
chat was in the batch, the view switches to a new chat (as single delete does). Undo
restores the batch with one call. After the toast is gone, the chats remain
restorable one by one from the Trash view.

**Failure.** On a request error the rows are restored, an error toast is shown, and
selection mode stays open with the selection intact so the user can retry.

**Exiting.** Cancel, Escape (desktop), or a completed delete.

## API

Both routes live in `src/api/routes/conversation_trash.py` on the shared
Conversations blueprint, with `@rate_limit_conversations` and `@require_auth`.
Schemas in `src/api/schemas/conversations.py`; client types regenerated with
`make openapi && make types`. POST rather than DELETE because both carry a body.

### `POST /api/conversations/bulk-trash`

Request body - exactly one of:

```json
{ "ids": ["c1", "c2"] }
```

```json
{ "all": true, "exclude_ids": ["c3"], "created_before": "2026-10-13T09:12:00+00:00" }
```

- `ids` and `exclude_ids` hold at most `CONVERSATIONS_BULK_MAX_IDS` entries.
- `all` must be `true` when present, and `created_before` is required with it.
- Any other shape (both forms, neither form, over the cap) is a 400 validation error.

Response: `{ "trashed_ids": [...] }` - only the rows this call changed. Unknown,
foreign, already-trashed and non-trashable ids are skipped silently; the response is
the source of truth.

Eligible rows: owned by the user, `deleted_at IS NULL`, and a regular chat (not
`is_agent`, `is_planning`, `is_sports`, `is_language`). In `all` mode additionally:
`pinned = 0`, `archived = 0`, `created_at < created_before`, and `id NOT IN exclude_ids`.

### `POST /api/conversations/bulk-restore`

Request `{ "ids": [...] }` (same cap); response `{ "restored_ids": [...] }` - rows
of the user's that were in the trash and now are not.

## Backend

New methods on `ConversationTrashMixin` (`src/db/models/conversation_trash.py`):

| Method | Behavior |
|--------|----------|
| `trash_conversations(user_id, ids)` | Trash the eligible rows among `ids`; return their ids |
| `trash_all_conversations(user_id, exclude_ids, created_before)` | Trash the select-all set; return its ids |
| `restore_conversations(user_id, ids)` | Clear `deleted_at` on the trashed rows among `ids`; return their ids |

Each selects the eligible ids and updates exactly those rows in one transaction (no
`UPDATE ... RETURNING`, which the codebase does not use yet), and sets `deleted_at` / `updated_at` exactly as the
single-row `trash_conversation` / `restore_conversation` do. The sync change log is
fed by row triggers, so bulk updates reach other devices with no sync changes; search
and semantic recall already filter on `deleted_at`, so no index work either.

One info log line per call: `user_id`, count, and mode (`ids` / `all` / `restore`).

New config: `CONVERSATIONS_BULK_MAX_IDS` (default 500) in `src/config.py` and
`.env.example`.

## Frontend

- `web/src/components/SidebarSelection.ts` (new): enter/exit, selection bar, footer
  button, row toggling, select-all counter. The list renderer in `Sidebar.ts` gets
  only a small hook to render rows with checkboxes in selection mode - `Sidebar.ts` is
  already over the file-size limit, so no new logic goes there.
- `web/src/state/slices/selection.ts` (new):
  `{ active, mode: 'ids' | 'all', ids, excludeIds, createdBefore }`.
- `web/src/api/conversations.ts`: `bulkTrash()` and `bulkRestore()`.
- `web/src/core/conversation-actions.ts`: `bulkDeleteConversations()` beside
  `deleteConversation` - optimistic removal, `noteLocalChange` for every affected id,
  Undo toast, rollback on error.

**Select-all counter.** `total_count` from the main list response minus the pinned
chats, minus the exclusions, plus pinned chats ticked by hand. This assumes all
pinned chats are loaded up front; verify during implementation, and if not, add the
pinned count to the list response instead.

## Edge cases

- **Unsaved chats** (temp ids) in the selection are removed locally and never sent.
- **Stale sync responses:** `noteLocalChange` on each affected id stops a sync
  response requested before the delete from bringing rows back.
- **Open chat in the batch:** cleared, view moves to a new chat.
- **Chat with a reply streaming:** behaves as single delete does today (confirm the
  exact behavior during implementation and match it).
- **Nothing eligible:** the button is disabled; if the server still returns an empty
  `trashed_ids`, close selection mode without a toast.
- **Batch vs streaming parity:** not affected - no chat-turn code changes.

## Testing

- **Backend (TDD):** DB tests per method - owner scoping, pinned / archived /
  special-chat exclusion, `created_before` cutoff, `exclude_ids`, idempotency
  (re-trash, re-restore). Route tests - both body forms, invalid shapes and the cap
  return 400, response ids, auth required.
- **Frontend unit:** selection slice transitions, counter arithmetic, rollback on error.
- **E2E (mock server, desktop and mobile viewports):** enter, pick 3, move to trash,
  Undo restores them; Select all, untick 1, delete - only that chat and pinned chats
  remain.
- **Visual:** sidebar in selection mode, desktop and mobile baselines (Linux
  baselines via `/regen-baselines`).

## Docs

- `docs/features/ui-features.md`: new "Bulk delete" subsection under Delete; bulk
  routes added to the Trash API table.
- `CONVERSATIONS_BULK_MAX_IDS` documented on that page.
