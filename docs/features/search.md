# Full-Text Search

The app supports cross-conversation full-text search using SQLite FTS5.

## Overview

The search system provides:
- Full-text search across conversation titles and message content
- Real-time search with debounced input (300ms)
- Porter stemming and Unicode support
- Search result highlighting with navigation
- O(1) message loading via `around_message_id`
- Persistent search results for multi-result navigation

## Architecture

### Search Index Design

```sql
CREATE VIRTUAL TABLE search_index USING fts5(
    user_id UNINDEXED,      -- For filtering, not searching
    conversation_id UNINDEXED,
    message_id UNINDEXED,
    type UNINDEXED,         -- 'conversation' or 'message'
    title,                  -- Conversation title (searchable)
    content,                -- Message content (searchable)
    tokenize='porter unicode61 remove_diacritics 2'
);
```

**Tokenizer features:**
- **Porter stemmer**: "running" matches "run", "programming" matches "program"
- **Unicode support**: Handles international characters correctly
- **Diacritic removal**: "cafe" matches "café"

### Trigger-Based Sync

Database triggers keep the search index in sync when conversations/messages are created, updated, or deleted. See [migrations/0015_add_full_text_search.py](../../migrations/0015_add_full_text_search.py).

## How It Works

### Search Flow

1. **Search activation**: Focus on search input activates search mode
2. **Debounced input**: 300ms debounce prevents excessive API calls
3. **API call**: `GET /api/search?q=query&limit=20&offset=0` returns matching results
4. **Result display**: Results replace conversation list with count header
5. **Highlighting**: Matched text wrapped in `[[HIGHLIGHT]]...[[/HIGHLIGHT]]` markers, converted to `<mark>` tags

### UI Behavior

**Search activation and deactivation:**
- Focus on search input to activate search mode
- Press Escape or click clear button (X) to exit search mode
- Works consistently on both desktop and mobile

**Result interaction:**
- Click result to navigate to conversation and centered message view
- Search results stay visible after clicking (persistent results)
- Clicked result is highlighted with `.active` class
- Active result tracked by index (not message ID) to handle duplicates

### Deduplication

The search index may contain duplicate entries due to trigger timing. Deduplication is handled in Python after fetching from the database because FTS5's `bm25()` and `snippet()` functions don't work with `GROUP BY`.

**Process:**
1. Fetch all matching results from FTS5 (ordered by relevance)
2. Deduplicate by `message_id` (for message matches) or `conversation_id` (for title matches)
3. Apply pagination (offset/limit) after deduplication
4. Return accurate total count of unique results

## Search Result Navigation (O(1) Optimization)

When navigating to a search result in a large conversation, the app uses `around_message_id` to load messages centered around the target in a single API call, rather than loading from newest until finding the target (which was O(n)).

### How It Works

1. User clicks search result with `message_id`
2. Frontend calls `GET /api/conversations/{id}/messages?around_message_id={message_id}&limit=100`
3. Backend's `get_messages_around()` loads ~50 messages before and ~50 after the target
4. Frontend replaces current messages with the centered page
5. Both scroll listeners (older/newer) are set up for bi-directional pagination
6. User can scroll up to load older messages, or down to load newer messages

### Edge Cases Handled

| Scenario | Handling |
|----------|----------|
| **Sending message after search navigation** | If `hasNewer` is true, `loadAllRemainingNewerMessages()` is called before sending to ensure no gap |
| **Rapid search result clicks** | `pendingSearchNavigationMessageId` tracking variable prevents stale API responses from rendering |
| **Conversation switch during navigation** | Guards check `currentConversation.id` after API call returns |
| **Image scroll interference** | `disableScrollOnImageLoad()` is called before `renderMessages()` so images don't override scroll-to-target behavior |
| **Sync manager false unread badges** | `markConversationRead()` is called with `total_count` after loading around messages to prevent false badges |
| **Scroll-to-bottom in partial view** | The scroll-to-bottom button callback loads all remaining newer messages first via `setBeforeScrollToBottomCallback` |
| **Newer scroll listener cleanup** | `cleanupNewerMessagesScrollListener()` is called in `switchToConversation()` to prevent old listeners from firing |
| **Search navigation during streaming** | If streaming is active in the same conversation, search navigation is blocked with a toast message |

### Key Functions

- `scrollToAndHighlightMessage()` in [search.ts](../../web/src/core/search.ts) - Orchestrates the navigation
- `loadAllRemainingNewerMessages()` in [messages/pagination.ts](../../web/src/components/messages/pagination.ts) - Loads all newer messages before send
- `get_messages_around()` in [models/](../../src/db/models/) - Backend method for centered pagination
- `getMessagesAround()` in [client.ts](../../web/src/api/client.ts) - Frontend API method

## Configuration

### Backend

```python
# src/config.py
SEARCH_MAX_QUERY_LENGTH = 200  # Maximum query length
SEARCH_MAX_LIMIT = 50          # Maximum results per page
MESSAGES_AROUND_BEFORE_DEFAULT = 50  # Messages before target
MESSAGES_AROUND_AFTER_DEFAULT = 50   # Messages after target
```

### Frontend

```typescript
// web/src/config.ts
SEARCH_DEBOUNCE_MS = 300              // Input debounce delay
SEARCH_HIGHLIGHT_DURATION_MS = 2000   // Message highlight animation duration
SEARCH_RESULT_MESSAGES_LIMIT = 100    // Messages to load when navigating to search result
LOAD_NEWER_MESSAGES_THRESHOLD_PX = 200 // Scroll threshold for loading newer messages
```

## Key Files

### Backend

- [migrations/0015_add_full_text_search.py](../../migrations/0015_add_full_text_search.py) - FTS5 table creation and triggers
- [models/](../../src/db/models/) - `SearchResult` dataclass, `search()` method with query escaping, `get_messages_around()`
- [routes/conversations.py](../../src/api/routes/conversations.py) - `GET /api/search` endpoint with validation
- [schemas.py](../../src/api/schemas.py) - `SearchResultResponse`, `SearchResultsResponse` schemas
- [config.py](../../src/config.py) - Configuration constants

### Frontend

- [SearchInput.ts](../../web/src/components/SearchInput.ts) - Search input component with debounce
- [SearchResults.ts](../../web/src/components/SearchResults.ts) - Results display and subscription
- [store.ts](../../web/src/state/store.ts) - Search state management
- [client.ts](../../web/src/api/client.ts) - `search.query()` API method
- [api.ts](../../web/src/types/api.ts) - Type definitions
- [search.ts](../../web/src/core/search.ts) - Navigation and highlight logic
- [config.ts](../../web/src/config.ts) - Configuration constants

### Styles

- [sidebar.css](../../web/src/styles/components/sidebar.css) - Search input, results, active result styles
- [messages.css](../../web/src/styles/components/messages.css) - `.search-highlight` class with outline-based pulse animation

## Testing

- **Backend unit tests**:
  - [test_search.py](../../tests/unit/test_search.py) - Query escaping, user boundaries
  - [test_messages_around.py](../../tests/unit/test_messages_around.py) - `get_messages_around()` method
- **Backend integration tests**:
  - [test_routes_search.py](../../tests/integration/test_routes_search.py) - API endpoint tests
  - [test_routes_messages_around.py](../../tests/integration/test_routes_messages_around.py) - `around_message_id` endpoint tests
- **E2E tests**: [search.spec.ts](../../web/tests/e2e/search.spec.ts) - Full search flow including pagination navigation
- **Visual tests**: [search.visual.ts](../../web/tests/visual/search.visual.ts) - Search UI screenshots
- **Mock server**: [e2e-server.py](../../tests/e2e-server.py) - `/test/set-search-results` and `/test/clear-search-results` endpoints

## See Also

- [Cursor-Based Pagination](../ui/scroll-behavior.md#cursor-based-pagination) - Message pagination system
- [Database Indexes](../architecture/database.md#indexes) - FTS5 index details
- [Testing Guide](../testing.md) - Testing patterns
