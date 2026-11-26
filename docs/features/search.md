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

**Lookup table** ([migration 0067](../../migrations/0067_add_search_index_keys.py)): the id columns are
`UNINDEXED`, so a trigger that deleted by `message_id` / `conversation_id` scanned the whole index -
once per deleted message, which made bulk deletes quadratic (a 1000-chat empty trash took minutes).
`search_index_keys(fts_rowid INTEGER PRIMARY KEY, conversation_id, message_id)` maps every index row
to its ids with ordinary b-tree indexes (`message_id` unique); the triggers insert the key first and
use its id as the FTS rowid, and delete through it. Its rowid is an explicit INTEGER PRIMARY KEY, so
VACUUM cannot renumber it (an implicit `messages.rowid` could). Any new trigger or code that writes
`search_index` must keep the two tables in step.

**Message text changes** ([migration 0101](../../migrations/0101_search_index_follows_message_edits.py),
Nov 17 2026): `fts_update_message` copies a message's new text into its index row and drops its
embedding. Before it there was no update trigger, so a reply saved as a placeholder and filled in
later kept its old, often empty, indexed text (16 of 320 assistant replies in a local copy; the
migration backfilled them), and an edited message would have stayed findable by its old text.

**Artifact titles** ([migration 0105](../../migrations/0105_search_artifact_titles.py), Nov 25
2026): every artifact has an index row (`type = 'artifact'`, its title, keyed by
`search_index_keys.artifact_id`) whose `message_id` is the reply that built version 1
(`fts_link_artifact`, set when the turn links its versions), so a hit opens that reply. The row
follows the artifact (`fts_insert_artifact`, `fts_update_artifact`, `fts_delete_artifact` - an
artifact's delete already follows its reply's and its chat's). `message_id` stays out of the key:
the message triggers rewrite or drop rows by `search_index_keys.message_id`. The chat-title trigger
re-keys rows with no `message_id`, so it now skips `artifact_id` rows. A hit's snippet is the
highlighted title ("Artifact" in the list, "(built the artifact)" for `search_conversations`).

Moving a conversation to the [trash](ui-conversations.md#trash) does not touch the index: the search query joins `conversations` and filters `c.deleted_at IS NULL`, so restoring needs no reindex. Rows leave the index only when the conversation is permanently deleted (purge, delete forever, empty trash).

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

### Any-word fallback (Nov 16 2026)

`Database.search` requires every word (each a prefix). When that finds fewer than
`CONVERSATION_SEARCH_FALLBACK_MIN_RESULTS` (3) results, it also runs an any-word query
(`fts_query(query, any_words=True)`: words ORed, words under 3 letters dropped, words of
6+ letters trimmed by 2 so Czech inflections match; a query of only short words skips the
fallback) and appends its new hits (`match_mode="any"`), reading at most `ANY_ROW_LIMIT`
(200) rows. A word with a single letter or digit ("C++" tokenizes to "c") is an exact
term, not a prefix. `/api/search` returns `match_mode` per result and the search list
labels fallback hits "Partial match" instead of "Message"/"Title". The index uses an English (porter) stemmer, so Czech word
forms otherwise only match by prefix. The app's search box and the agent's
`search_conversations` both use it; `after`/`before` (UTC instants) bound message hits by
their time and title hits by any of the conversation's messages. A query FTS5 still
rejects after escaping returns no results and logs "Search query rejected".

### Embeddings follow their message

Migration 0095 (Nov 16 2026) purged 26.1k message embeddings of deleted messages and added
a trigger deleting a message's embedding whenever the message is deleted (every path:
one message, a truncation, a conversation, the trash purge). Trashed conversations keep
theirs until the purge, so a restored chat is found by meaning again.

### Deduplication

The search index could contain duplicate entries due to trigger timing (migration 0067 removed them and keys each message to one row; titles are re-keyed on rename). Deduplication is handled in Python after fetching from the database because FTS5's `bm25()` and `snippet()` functions don't work with `GROUP BY`.

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
| **Page load in flight during the jump** (Nov 2026) | An older/newer page requested against the previous window would be inserted into the re-rendered one and duplicate messages (a double-clicked result rendered the target twice). `renderMessages()` bumps a render generation (`getRenderGeneration()`); the loaders drop a response whose generation changed, and only the latest load of a kind resets its loading flag and loader. A conversation-id check alone cannot catch this - the conversation is the same |
| **A page moved the other edge's cursor** (Nov 26 2026) | After a jump (a window mid-chat), scrolling up then down rendered the window again below itself (102 duplicates in a 300-message chat). The server marks an older page `has_newer` with a newer cursor at its own newest message, and `prependMessages` adopted the page's whole pagination, so the next newer load re-fetched the window; `appendMessages` did the same to the older side. A page now updates only its own edge's cursor, `has_*` and loading flag (`withMessagesPage` in `state/slices/messages.ts`). |
| **Image scroll interference** | `disableScrollOnImageLoad()` is called before `renderMessages()` so images don't override scroll-to-target behavior |
| **Sync manager false unread badges** | `markConversationRead()` is called with `total_count` after loading around messages to prevent false badges |
| **Scroll-to-bottom in partial view** | The scroll-to-bottom button callback loads all remaining newer messages first via `setBeforeScrollToBottomCallback` |
| **Newer scroll listener cleanup** | `cleanupNewerMessagesScrollListener()` is called in `switchToConversation()` to prevent old listeners from firing |
| **Search navigation during streaming** | If streaming is active in the same conversation, search navigation is blocked with a toast message |

### Key Functions

- `scrollToAndHighlightMessage()` in [search.ts](../../web/src/core/search.ts) - Orchestrates the navigation
- `loadAllRemainingNewerMessages()` in [messages/pagination.ts](../../web/src/components/messages/pagination.ts) - Loads all newer messages before send
- `get_messages_around()` in [models/](../../src/db/models/) - Backend method for centered pagination
- `getMessagesAround()` in [api/conversations.ts](../../web/src/api/conversations.ts) - Frontend API method

## Configuration

### Backend

```python
# src/config.py
SEARCH_MAX_QUERY_LENGTH = 200  # Maximum query length
SEARCH_MAX_LIMIT = 50          # Maximum results per page
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
- [routes/conversation_search.py](../../src/api/routes/conversation_search.py) - `GET /api/search` endpoint with validation
- [schemas/conversations.py](../../src/api/schemas/conversations.py) - `SearchResultResponse`, `SearchResultsResponse` schemas
- [config.py](../../src/config.py) - Configuration constants

### Frontend

- [SearchInput.ts](../../web/src/components/SearchInput.ts) - Search input component with debounce
- [SearchResults.ts](../../web/src/components/SearchResults.ts) - Results display and subscription
- [store.ts](../../web/src/state/store.ts) - Search state management
- [api/search.ts](../../web/src/api/search.ts) - `search.query()` API method
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
  - [test_routes_conversation_search.py](../../tests/integration/test_routes_conversation_search.py) - API endpoint tests
  - [test_routes_conversation_messages.py](../../tests/integration/test_routes_conversation_messages.py) - `around_message_id` endpoint tests
- **E2E tests**: [search.spec.ts](../../web/tests/e2e/search.spec.ts) - Full search flow including pagination navigation
- **Visual tests**: [search.visual.ts](../../web/tests/visual/search.visual.ts) - Search UI screenshots
- **Mock server**: [control_routes.py](../../tests/e2e_server/control_routes.py) - `/test/set-search-results` and `/test/clear-search-results` endpoints

## See Also

- [Cursor-Based Pagination](../ui/scroll-behavior.md#cursor-based-pagination) - Message pagination system
- [Database Indexes](../architecture/database.md#database-indexes) - FTS5 index details
- [Testing Guide](../testing.md) - Testing patterns
