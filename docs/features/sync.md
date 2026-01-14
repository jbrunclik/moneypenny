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

2. **Incremental sync**: Every 60 seconds
   - Fetches only conversations updated since last sync
   - Uses `since` timestamp parameter

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

### New Messages Banner

Appears at top of messages when current conversation has external updates (messages added from another device/tab).

**Behavior:**
- Doesn't auto-inject messages (preserves scroll position)
- User clicks banner to reload and see new messages

## Race Condition Handling

The SyncManager handles several race conditions:

### 1. Concurrent Sync Prevention

`isSyncing` lock prevents multiple syncs from running simultaneously.

### 2. Streaming Protection

Conversations being actively streamed are skipped during sync to prevent false unread counts.

### 3. Clock Skew

Always uses `server_time` from response, never client time.

### 4. Message Boundary

Server returns `server_time` that becomes next sync's `since` param.

### 5. Streaming Completion Race

When streaming completes, the local message count must be incremented BEFORE clearing the streaming flag.

**Critical ordering in `sendStreamingMessage()` finally block:**
```typescript
// CORRECT ORDER - prevents race condition
if (messageSuccessful) {
  getSyncManager()?.incrementLocalMessageCount(convId, 2);  // 1. Increment count FIRST
}
getSyncManager()?.setConversationStreaming(convId, false);   // 2. THEN clear streaming flag
```

The same pattern applies to `sendBatchMessage()` where `incrementLocalMessageCount()` is called after successful response processing, before the function returns.

### 6. Pagination Count Mismatch

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

### 7. Paginated FullSync Discovery

When fullSync returns conversations beyond the initial paginated load (e.g., user's 50th conversation when only 30 were loaded), these are NOT "unread" - they're newly discovered.

**Handling:**
- The SyncManager initializes `localMessageCounts` to the server's count for these conversations, preventing false unread badges
- The store's `addConversation()` inserts at the correct sorted position (by `updated_at` DESC) rather than prepending

## Delete Detection

Full sync compares local conversation IDs with server response:
- Conversations missing from server are removed from local state
- Shows toast if user was viewing a deleted conversation

## Edge Cases Handled

| Scenario | Handling |
|----------|----------|
| **Clock skew** | Always uses `server_time` from response, not client time |
| **Race on send** | User sends message, poll happens before save - not a problem (optimistic UI) |
| **Viewing updated conversation** | Shows "New messages" banner, doesn't auto-inject |
| **Offline → Online** | On visibility change, syncs immediately |
| **Deleted while viewing** | Shows toast and clears current conversation |
| **Temp conversations** | Not synced (start with `temp-` prefix, not yet persisted) |

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
- [models.py](../../src/db/models.py) - `list_conversations_with_message_count()`, `get_conversations_updated_since()`

### Frontend

- [SyncManager.ts](../../web/src/sync/SyncManager.ts) - Polling, state sync, race condition handling
- [api/client.ts](../../web/src/api/client.ts) - `conversations.sync()` method
- [main.ts](../../web/src/main.ts) - SyncManager initialization, new messages banner, streaming integration
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
- **E2E**: [pagination.spec.ts](../../web/tests/e2e/pagination.spec.ts) - "Pagination with Sync - Edge Cases"
- **Visual**: [chat.visual.ts](../../web/tests/visual/chat.visual.ts) - Sync UI visual tests (unread badge, banner)

## Future Optimizations

- Consider soft delete (`deleted_at` column) for more efficient delete detection
- BroadcastChannel for multi-tab coordination if needed

## See Also

- [Cursor-Based Pagination](../ui/scroll-behavior.md#cursor-based-pagination) - Message pagination affecting sync counts
- [Concurrent Request Handling](chat-and-streaming.md#concurrent-request-handling) - How streaming affects sync
- [Testing Guide](../testing.md) - Testing patterns for sync scenarios
