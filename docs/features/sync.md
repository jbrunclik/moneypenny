# Real-Time Synchronization

The app syncs conversation state across multiple devices/tabs using timestamp-based polling.

## Architecture Decision: Polling over SSE/WebSockets

The app uses timestamp-based polling with `updated_at` instead of SSE or WebSockets because:

1. **Simplicity**: No new infrastructure or persistent connections to manage
2. **Already indexed**: Uses existing `idx_conversations_user_id_updated_at` composite index
3. **No write overhead**: `updated_at` is already updated on message addition
4. **Appropriate scale**: Single-user/small-user app (email whitelist)
5. **Robust**: Each poll is independent, no reconnection logic needed

## How It Works

### Sync Modes

1. **Full sync**: On initial load or after >5 minutes hidden
   - Fetches all conversations with message counts
   - Detects deleted conversations by comparing local IDs with server response
   - Adds genuinely new conversations created on other devices (after initialLoadTime)
   - Pagination-discovered conversations (older than initialLoadTime) are NOT added

2. **Incremental sync**: Every 60 seconds - the **change log** (Oct 2026)
   - Asks for every conversation changed after the client's `cursor` (`?cursor=N`); the full sync returns the starting cursor
   - Each change carries the conversation's state: `archived`, `trashed`, `pinned`, `last_message_id`, plus `removed_ids` for permanent deletes - so archive / trash / delete / pin / restore from another device apply on the next tick (the timestamp sync only noticed removals on a full sync, which a visible tab never ran)
   - Pages while `has_more` (`SYNC_CHANGES_PAGE_SIZE` per response, `SYNC_MAX_CHANGE_PAGES` per tick)
   - Falls back to the legacy `since` timestamp sync against a server without the change log

### Change log ([migration 0061](../../migrations/0061_add_sync_change_log.py))

SQLite **triggers** on `conversations` and `messages` (insert / update / delete) bump a global `sync_counter` and upsert the conversation's row in `conversation_changes(conversation_id, user_id, seq)` - in the same transaction as the write, for every write path including future ones. SQLite serializes writers, so seq order is commit order: a cursor can't skip a change the way the `updated_at`-vs-`server_time` comparison could (a commit landing after the snapshot), and there's no clock/DST dependence. A permanently deleted conversation keeps its change row as a tombstone (`conversation` NULL on read → `removed_ids`). Non-chat conversations (planner, agents, programs) advance the cursor but aren't returned - they keep their own syncs.

On the client (`applyChangeLog` in SyncManager): a removal closes the open conversation with a notice (an **archived** one stays open, it's still readable); a conversation that (re)appears is added when it falls inside the loaded part of the list (older ones come with pagination), counted unread only beyond its known count - a restore or unarchive isn't "new".

3. **Visibility-aware polling**:
   - Polling pauses when tab is hidden
   - Syncs immediately on refocus

### Sync Endpoint

```
GET /api/conversations/sync?since={ISO_TIMESTAMP}&full={BOOLEAN}
```

**Query params:**
- `since`: ISO timestamp - return conversations updated after this time
- `full`: Boolean - if true, return all conversations (for delete detection)

**Note:** Only returns regular conversations. Planner conversations (`is_planning=1`) and autonomous agent conversations (`is_agent=1`) are filtered out at the database level. They have separate sync mechanisms.

**Response:**
```json
{
  "conversations": [
    {"id": "...", "title": "...", "message_count": 10, "updated_at": "..."}
  ],
  "server_time": "2024-01-01T12:00:00.000000",
  "is_full_sync": false
}
```

### Unread Count Calculation

**Shared read state (Oct 2026, [migration 0062](../../migrations/0062_add_conversation_read_count.py)).** `conversations.read_message_count` is the message count as of the last time ANY of the user's devices showed the conversation; badges are `message_count - read_count`, from the conversation list on first paint and from every sync summary (`read_count`). A device reports it via `POST /conversations/<id>/read` (`reportRead` in SyncManager, deduplicated) when it shows a conversation (`markConversationRead`) and when its own turn ends (`setLocalMessageCount`: the full count if the chat is open, count - 1 if the user switched away - their own message is read, the reply isn't). The write is a conversation UPDATE, so the change log carries "read" to the other devices; `updated_at` is untouched (no reordering) and an unchanged count doesn't write. Existing conversations started fully read; `/test/seed` marks seeded history read unless `"unread": true`.

The local counts below remain only for the OPEN conversation's change detection (merge trigger) and for servers without `read_count`:

```
unreadCount = server_message_count - local_message_count
```

- Shown as badge on sidebar conversation items
- Badge shows "99+" for counts over 99
- Cleared when user clicks the conversation

## UI Indicators

### Unread Badge

Shows count on conversations with new messages in the sidebar.

**Badge clearing:**
When user clicks a conversation, `switchToConversation()` calls both:
1. `markConversationRead()` - Updates store state
2. `renderConversationsList()` - Re-renders sidebar

### Open conversation: in-place merge (Oct 2026)

When the open chat changes on another device ([core/remote-merge.ts](../../web/src/core/remote-merge.ts)), `mergeExternalChanges()` fetches the latest page and diffs it against what is rendered - no banner, no reload:
- **New messages** are appended in place; scroll position, drafts and pending sends survive. At the bottom the view follows; further up, the scroll button becomes the "New messages" pill (`showNewMessagesPill`, cleared at the bottom).
- **Deleted / regenerated / edited** rendered messages fall back to a full re-render (`reloadCurrentConversation`).
- **A reply still streaming on the other device**: its empty placeholder is filtered from API responses, so `GET /conversations/<id>` reports `streaming_message_id` (newest page, younger than `CHAT_TIMEOUT`); the client follows it live through the stream journal's resume endpoint (`followRemoteStream` in stream-resume.ts - the journal is per user, not per device). Opening such a conversation does the same (`followRemoteStreamOnOpen`). Another device's stream never anchors the view unless the reader is at the bottom.
- Skipped while this tab runs its own turn there (the deferred summary re-triggers it) or shows an older window (`hasNewer`).
- Triggered on ANY change-log change to the open chat, not just a higher count (a delete, a regenerate or a finished remote stream leave it equal); diffing makes our own changes a no-op.

The planner and agent views still show the "New messages available - Reload" banner.

**Pitfall:** the `initSyncManager` callbacks in core/init.ts must read `useStore.getState()` live - the `store` const there is a startup snapshot (Zustand replaces the state object on every update). Reading `store.isPlannerView` / `store.currentConversation` from it meant the planner deleted/reset/new-messages and agent handlers never fired.

## Race Condition Audit (Oct 10 2026)

A full data-flow audit found and fixed these (tests in `sync-manager.test.ts`, `sync-other-device.spec.ts`, `test_conversation_read_state.py`, `test_routes_interject.py`):
- **Full sync vs local creation**: only conversations known BEFORE the request can be "missing" from its answer (one created/restored/unarchived meanwhile was removed, open -> "deleted").
- **Stale in-flight polls**: local changes (`noteLocalChange` - rename, pin, archive, trash, restore, anonymous, title) make a response requested before them skip that conversation; colliding incremental syncs are queued, not dropped.
- **Own echoes**: the interject bubble and its saved message share an id (`client_message_id`), and a delete leaves the store too - otherwise every steered turn / delete looked like a vanished message and forced a full re-render. The re-render fallback goes through `showLoadedConversation` (keeps outbox sends, anonymous mode, archived/streaming state).
- **Open conversation**: merges run for the conversation open when they run (a switch mid-merge lost the new one's); an open archived chat merges (no "archived on another device" from its own echo); an open chat outside the loaded list still merges.
- **Read state** only moves forward (`MAX`) - a device that switched away reporting count-1 can't undo another's read - and deletes clamp it (migration 0063 trigger). The dedupe follows the server's `read_count`; our own message is reported read when the server saves it (`noteOwnMessageSaved`).
- **Anonymous mode** is in the summaries and adopted both ways (it was only ever set to true locally).
- **Remote stream follow**: a failed follow ends silently (no recovery toasts on a device that sent nothing); the follow window covers deep research; a reload-resume entry only replays when the server reports that reply in flight (another tab's / a finished turn's stale entry blocked the follow).
- **Lifecycle**: a bfcache restore without `visibilitychange` resumes polling; `stop()` during the initial sync leaves no zombie poller; the full sync adds by the loaded list window, not `initialLoadTime` (a conversation created elsewhere while this page booted was lost); pins apply on full syncs; the planner reset baseline follows this device's own resets; a generated title applies to its own conversation (not whichever is open).

## Race Condition Handling

The SyncManager handles several race conditions:

### 1. Concurrent Sync Prevention

`isSyncing` lock prevents multiple syncs from running simultaneously. A **full** sync requested while the lock is held is queued (`fullSyncQueued`) and runs when the holder finishes - dropping it lost the resume-time full sync whenever a frozen iOS poll timer fired first. The `online` event also triggers a full sync.

### 2. Own-turn Protection (stream AND batch)

Conversations with a turn running on this device (streaming, or a batch request in flight) are skipped during sync to prevent false unread counts from our own messages. The skipped summary is kept (`deferredUpdates`) and applied when the turn ends - the poll cursor has moved past it, so dropping it lost the other device's rename/messages until their next change.

### 3. Clock Skew

Always uses `server_time` from response, never client time.

### 4. Message Boundary

Server returns `server_time` that becomes next sync's `since` param.

### 5. Server Time Capture Timing

**Critical:** The backend captures `server_time` BEFORE running the database query, not after.

```python
# CORRECT - capture BEFORE query
server_time = datetime.now()
conv_with_counts = db.get_conversations_updated_since(user.id, since_dt)
```

If captured after the query, a conversation created/updated between the query and timestamp assignment would be missed forever (the cursor advances past it).

### 6. Streaming Completion Race

When a turn completes, the local message count must be set BEFORE clearing the streaming flag (clearing it applies the deferred summary against the baseline). The count is the server's exact one: the done event and the batch response carry `message_count` (`conversation_message_count()` in `src/api/utils.py`). The old `+2` guess drifted on regenerate/continue (server change 0/+1) and the inflated baseline hid the other device's next messages.

**Critical ordering in `cleanupStreamingRequest()` ([stream-session.ts](../../web/src/core/stream-session.ts)), called from the `sendStreamingMessage()` finally block:**
```typescript
// CORRECT ORDER - prevents race condition
if (serverMessageCount !== undefined) {
  getSyncManager()?.setLocalMessageCount(convId, serverMessageCount); // 1. Baseline FIRST
}
getSyncManager()?.setConversationStreaming(convId, false);             // 2. THEN clear the flag
```

The same pattern applies to `completeBatchTurn()` - which sets the baseline first thing, even when the user switched away (returning before it left our own turn as "unread 2"). `setLocalMessageCount` also moves the planner / agent view baselines when that view is open, so our own messages there don't raise their "new messages" banner.

An older conversation continued on another device (known from the full sync but not loaded in the sidebar) shows only the messages beyond its known count as unread, not its whole history.

### 7. Pagination Count Mismatch

When opening an existing conversation with pagination, use `message_pagination.total_count` (NOT `conv.messages.length`) to set the baseline message count.

**Critical: Use total_count for marking conversations as read:**
```typescript
// In selectConversation() - use pagination total, NOT messages.length
switchToConversation(conv, response.message_pagination.total_count);

// In switchToConversation() - use provided total or fall back to messages.length
const messageCount = totalMessageCount ?? conv.messages?.length ?? 0;
getSyncManager()?.markConversationRead(conv.id, messageCount);
```

Without this, an existing conversation with 100 messages but only 50 loaded (pagination) would set `localMessageCount=50`. After streaming adds 2 messages, `localCount=52` but `serverCount=102` → false "new messages available" banner.

### 8. Paginated FullSync Discovery

When fullSync returns conversations beyond the initial paginated load (e.g., user's 50th conversation when only 30 were loaded), these are NOT "unread" - they're newly discovered.

**Handling:**
- The SyncManager initializes `localMessageCounts` to the server's count for these conversations, preventing false unread badges
- The store's `addConversation()` inserts at the correct sorted position (by `updated_at` DESC) rather than prepending

## Delete Detection

Full sync compares local conversation IDs with server response:
- Conversations missing from server are removed from local state
- Shows toast if user was viewing a deleted conversation
- A conversation moved to the [trash](ui-features.md#trash) on another device counts as deleted: sync
  queries filter `deleted_at IS NULL`, so it simply stops appearing
- Since the change log, incremental syncs remove trashed / archived / deleted conversations directly; the full sync remains the safety net (start, >5 min hidden, `online`)

## Edge Cases Handled

| Scenario | Handling |
|----------|----------|
| **Clock skew** | Always uses `server_time` from response, not client time |
| **Race on send** | User sends message, poll happens before save - not a problem (optimistic UI) |
| **Viewing updated conversation** | Merged in place (`remote-merge.ts`); another device's live reply streams in |
| **Offline → Online** | `online` event runs a full sync; visibility change syncs immediately |
| **Archived / trashed / deleted / pinned / restored elsewhere** | Change log: applied on the next tick (E2E: `sync-other-device.spec.ts`) |
| **Deleted while viewing** | Shows toast and clears current conversation |
| **Temp conversations** | Not synced (start with `temp-` prefix, not yet persisted) |
| **Remote conv created while hidden** | Full sync adds genuinely new conversations (created after initialLoadTime) with unread badge |

## Configuration

### Backend

```python
# src/config.py
SYNC_POLL_INTERVAL_SECONDS = 60  # Not currently used by backend (frontend-only polling)
```

### Frontend

```typescript
// web/src/config.ts
SYNC_POLL_INTERVAL_MS = 60 * 1000;           // 1 minute
SYNC_FULL_SYNC_THRESHOLD_MS = 5 * 60 * 1000; // 5 minutes
```

## Key Files

### Backend

- [routes/conversations.py](../../src/api/routes/conversations.py) - `GET /api/conversations/sync` endpoint
- [models/](../../src/db/models/) - `list_conversations_with_message_count()`, `get_conversations_updated_since()`

### Frontend

- [SyncManager.ts](../../web/src/sync/SyncManager.ts) - Polling, state sync, race condition handling
- [api/conversations.ts](../../web/src/api/conversations.ts) - `conversations.sync()` method
- [init.ts](../../web/src/core/init.ts) - SyncManager initialization
- [sync-banner.ts](../../web/src/core/sync-banner.ts) - New messages banner
- [Sidebar.ts](../../web/src/components/Sidebar.ts) - Unread badge rendering
- [config.ts](../../web/src/config.ts) - Configuration constants

### Styles

- [sidebar.css](../../web/src/styles/components/sidebar.css) - `.unread-badge` styles
- [messages.css](../../web/src/styles/components/messages.css) - `.new-messages-banner` styles

### Types

- [api.ts](../../web/src/types/api.ts) - `ConversationSummary`, `SyncResponse` types, sync fields on `Conversation`

## Testing

- **Backend integration**: [test_routes_sync.py](../../tests/integration/test_routes_sync.py) - Sync endpoint tests
- **Backend unit**: [test_db_models.py](../../tests/integration/test_db_models.py) - Sync database methods
- **Frontend unit**: [sync-manager.test.ts](../../web/tests/unit/sync-manager.test.ts) - SyncManager tests
- **E2E**: [sync.spec.ts](../../web/tests/e2e/sync.spec.ts) - Multi-tab and visibility scenarios
- **E2E**: [sync-other-device.spec.ts](../../web/tests/e2e/sync-other-device.spec.ts) - Another device (the API) archives / trashes / deletes / restores / pins / renames; only the regular poll tick (`window.__testIncrementalSync`), never a full sync
- **Backend**: [test_db_sync_changes.py](../../tests/integration/test_db_sync_changes.py) - every write path bumps the change seq (triggers)
- **E2E**: [pagination.spec.ts](../../web/tests/e2e/pagination.spec.ts) - "Pagination with Sync - Edge Cases"
- **Visual**: [chat.visual.ts](../../web/tests/visual/chat.visual.ts) - Sync UI visual tests (unread badge, banner)

## Future Optimizations

- Use the `deleted_at` column (added for the trash) to report deletions incrementally instead of via full-sync ID comparison
- BroadcastChannel for multi-tab coordination if needed

## See Also

- [Cursor-Based Pagination](../ui/scroll-behavior.md#cursor-based-pagination) - Message pagination affecting sync counts
- [Concurrent Request Handling](chat-and-streaming.md#concurrent-request-handling) - How streaming affects sync
- [Testing Guide](../testing.md) - Testing patterns for sync scenarios
