# Memory and Context

The app provides several features for personalizing LLM behavior: user context, user memory, custom instructions, and anonymous mode.

## User Context

The LLM system prompt can include user context to provide more personalized and contextually appropriate responses.

### Configuration

```bash
# .env
USER_LOCATION=Prague, Czech Republic  # Or "New York, USA", etc.
```

When `USER_LOCATION` is set, the LLM is instructed to:
- Use appropriate measurement units (metric vs imperial) based on local conventions
- Prefer local currency when discussing prices
- Recommend locally available retailers/services when relevant
- Consider local regulations, holidays, and cultural context
- Use appropriate date/time formats for the locale

### How It Works

1. **Location from config**: `USER_LOCATION` is read from environment/config (shared across all users of this deployment)
2. **User name from JWT**: The authenticated user's name is passed from the JWT token
3. **System prompt injection**: `get_user_context()` in prompts.py builds the context section
4. **Prompt integration**: `get_system_prompt()` includes the user context when building the system prompt

### Key Files

- [config.py](../../src/config.py) - `USER_LOCATION` configuration
- [prompts.py](../../src/agent/prompts.py) - `get_user_context()`, `get_system_prompt()` with `user_name` parameter
- [routes/chat.py](../../src/api/routes/chat.py) - Passes `user_name` from authenticated user to chat methods

---

## User Memory

The LLM can learn and remember facts about the user across conversations for personalization.

### Design Decisions

- **The tool performs the writes**: `manage_memory` writes during the turn and returns a
  result line per operation (new IDs, or a `REJECTED` line with the reason). It used to be
  a no-op stub whose args were replayed after the turn, which meant every rejection was
  logged server-side while the model was told it had succeeded. **Dev guardrail:** because it
  now has a real side effect whose result the model must read, `manage_memory` must never be
  added back to `EXTRACT_ONLY_TOOL_NAMES` in
  [`src/agent/tools/metadata.py`](../../src/agent/tools/metadata.py) — only true extract-only
  tools belong there (`cite_sources`, `set_conversation_title`; there is a regression test
  for this).
- **Delete only (for the user)**: users can view, delete and protect memories, but not edit
  their text (prevents fake memories)
- **Soft delete**: deletes are recoverable for `MEMORY_SOFT_DELETE_RETENTION_DAYS`
- **One limit**: `MEMORY_MAX_ENTRIES` is both what the LLM is told and what writes enforce
- **LLM deduplication**: the LLM sees existing memories and decides to update/consolidate
- **Categories**: `preference`, `fact`, `context`, `goal`

### How It Works

1. **Instructions**: `MEMORY_SYSTEM_PROMPT` is static, so it lives in the cached prompt prefix
2. **Injection**: the current memory list (with IDs, dates and protection flags) is added to
   the per-request dynamic context
3. **Writes**: the model calls `manage_memory`, which validates, writes, and reports the
   outcome so the model can correct course
4. **Management**: users view/delete/protect memories on the **Data page**
   ([`KVStorePage.ts`](../../web/src/components/KVStorePage.ts)), reached via the
   "Memories & Storage" button in the sidebar. (The old `MemoriesPopup` was removed — the
   memories UI now lives on the Data page alongside the K/V namespaces.)

### Memory Operations

```python
manage_memory(operations=[
    {"action": "add", "content": "Prefers dark mode", "category": "preference"},
    {"action": "update", "id": "<memory id>", "content": "Now prefers light mode"},
    {"action": "delete", "id": "<memory id>"},
])
```

The tool returns one line per operation, e.g.:

```
added id=6f2c... (7/200 used)
REJECTED (update): no memory with id=bogus (it may have been deleted or consolidated).
REJECTED (delete): id=9ab1... is protected by the user and cannot be deleted.
```

### Bounds and Safety

Memories are injected into every non-anonymous request, so unbounded writes mean unbounded
cost - and because the operation list can be shaped by fetched web content, they are also a
prompt-injection persistence vector. The enforced bounds:

| Setting | Default | Purpose |
|---|---|---|
| `MEMORY_MAX_ENTRIES` | 200 | Bank size; also the number shown to the LLM |
| `MEMORY_MAX_ENTRY_CHARS` | 500 | Per-entry size; oversized writes are rejected, not truncated |
| `MEMORY_WARNING_THRESHOLD` | 80% of max | Point at which the LLM is told to consolidate |
| `MEMORY_MAX_OPS_PER_CALL` | 10 | Per-call write budget, bounding a mass rewrite |
| `MEMORY_SOFT_DELETE_RETENTION_DAYS` | 7 | Recovery window for deleted memories |

Additional guards:

- **Protected memories** (`protected` column) cannot be deleted by the LLM or the defrag
  job - only by the user. This replaces the prompt-only "never delete family facts" rule.
- **Provenance** (`source_conversation_id`) records which conversation taught each memory.
- **Autonomous agents** only get `manage_memory` if it is in their `tool_permissions`
  (or they run unrestricted). An unattended agent that reads the web must not be able to
  persist attacker-controlled text into memory. Enforced both at tool binding and at call
  time via `check_autonomous_permission`.
- **Anonymous mode** does not bind the tool at all, so no write can be attempted.

### Episodic Recall (Conversation Search)

Memory holds a small set of curated facts. Everything else that was ever discussed is
reachable through search instead, which is what keeps the bank small:

- `search_conversations(query, limit)` - FTS5 keyword search over the user's own history,
  excluding the current conversation (already in context)
- `read_conversation(conversation_id, max_messages)` - read the full exchange behind a match

Both are withheld in anonymous mode. Bounds: `CONVERSATION_SEARCH_MAX_RESULTS`,
`CONVERSATION_READ_MAX_MESSAGES`, `CONVERSATION_READ_MAX_CHARS_PER_MESSAGE`.

### Key Files

**Backend:**
- [migrations/0009_add_user_memories.py](../../migrations/0009_add_user_memories.py) - initial table
- [migrations/0046_add_memory_provenance_and_soft_delete.py](../../migrations/0046_add_memory_provenance_and_soft_delete.py) - protection, provenance, soft delete
- [tools/memory.py](../../src/agent/tools/memory.py) - the `manage_memory` tool (validation + writes + feedback)
- [tools/conversation_search.py](../../src/agent/tools/conversation_search.py) - `search_conversations`, `read_conversation`
- [models/memory.py](../../src/db/models/memory.py) - `Memory` CRUD, soft delete, purge, protection
- [prompts.py](../../src/agent/prompts.py) - `MEMORY_SYSTEM_PROMPT`, `get_memory_instructions_prompt()` (static/cached), `get_user_memories_list_prompt()` (dynamic)
- [routes/memory.py](../../src/api/routes/memory.py) - list, delete, restore, protection endpoints
- [config.py](../../src/config.py) - the settings tabled above

**Frontend:**
- [KVStorePage.ts](../../web/src/components/KVStorePage.ts) - the Data page: memory list, delete,
  protect, and a "Recently deleted" section with restore
- [client.ts](../../web/src/api/client.ts) - `memories.*` API methods
- [api.ts](../../web/src/types/api.ts) - `Memory`, `MemoriesResponse` types
- [tool_display.py](../../src/agent/tool_display.py) - memory writes appear in the tool trace
  ("remembered 2, updated 1") so the user sees them as they happen

### Testing

- **Tool behaviour**: [test_memory_tool.py](../../tests/unit/test_memory_tool.py) - asserts on
  what the *model* is told, since a rejection it cannot read is a bug
- **Conversation search**: [test_conversation_search_tool.py](../../tests/unit/test_conversation_search_tool.py)
- **DB layer**: [test_db_memories.py](../../tests/integration/test_db_memories.py) - soft delete,
  protection, provenance, timestamp conventions
- **Routes**: [test_routes_kv_memory_system.py](../../tests/integration/test_routes_kv_memory_system.py)
- **Visual tests**: [popups.visual.ts](../../web/tests/visual/popups.visual.ts)

### Memory Defragmentation

A nightly systemd timer consolidates and cleans up user memories using an LLM.

**When it runs:**
- Nightly at 3:30 AM (with up to 30 min random delay)
- Only processes users with >= `MEMORY_DEFRAG_THRESHOLD` memories (default: 30)
- Uses `MEMORY_DEFRAG_MODEL` for quality consolidation

**What it does:**
1. Purges soft-deleted memories past the retention window
2. Merges related memories and removes duplicates
3. Keeps newer information when memories contradict
4. Removes vague or stale memories
5. Leaves protected memories alone

**Guards** (the job is not a privileged path into the bank):
- The plan is requested as a **schema** (`DefragPlan`), not parsed out of prose - a run that
  silently no-ops because the model wrapped its JSON differently is invisible
- Proposed writes go through the same size and category validation as the tool
- A plan that would **grow** the bank (more adds than deletes) is refused - the likeliest
  failure mode is the model writing a consolidated memory and forgetting to delete the originals
- Deletes are soft, so a bad run is recoverable
- Below the warning threshold the job stops asking for a percentage cut and only merges
  genuine duplicates

**Manual execution:**
```bash
make defrag-memories              # Run defragmentation
make defrag-memories -- --dry-run # Preview changes without applying
```

**Key files:**
- [defragment_memories.py](../../scripts/defragment_memories.py) - the job
- [ai-chatbot-memory-defrag.service](../../systemd/ai-chatbot-memory-defrag.service) / [.timer](../../systemd/ai-chatbot-memory-defrag.timer)
- Unit tests: [test_defragment_memories.py](../../tests/unit/test_defragment_memories.py)

---

## Custom Instructions

Users can customize LLM behavior via a free-text custom instructions field in the settings popup.

### How It Works

1. **Storage**: Custom instructions are stored in the `users.custom_instructions` column (up to 2000 characters)
2. **UI**: Settings popup accessible via gear icon button in sidebar (next to memories and logout)
3. **Injection**: Instructions are appended to the system prompt via `CUSTOM_INSTRUCTIONS_PROMPT` constant
4. **Immediate effect**: Changes apply to new messages immediately (no restart needed)

### Example Use Cases

- "Respond in Czech"
- "Be concise, use bullet points"
- "Explain things like I'm a beginner"
- "Always provide code examples in Python"

### API Endpoints

- `GET /api/users/me/settings` - Returns `{ custom_instructions: string }`
- `PATCH /api/users/me/settings` - Updates settings, body: `{ custom_instructions: string | null }`

### Key Files

**Backend:**
- [migrations/0010_add_custom_instructions.py](../../migrations/0010_add_custom_instructions.py) - Database migration
- [models/](../../src/db/models/) - `User.custom_instructions` field, `update_user_custom_instructions()` method
- [prompts.py](../../src/agent/prompts.py) - `CUSTOM_INSTRUCTIONS_PROMPT` constant, `get_system_prompt()` with `custom_instructions` parameter
- [schemas.py](../../src/api/schemas.py) - `UpdateSettingsRequest` schema with 2000 char limit
- [routes/settings.py](../../src/api/routes/settings.py) - Settings endpoints
- [routes/chat.py](../../src/api/routes/chat.py) - Passes `custom_instructions` to agent

**Frontend:**
- [SettingsPopup.ts](../../web/src/components/SettingsPopup.ts) - Settings popup with textarea, character count, save button
- [Sidebar.ts](../../web/src/components/Sidebar.ts) - Gear icon button in user actions
- [client.ts](../../web/src/api/client.ts) - `settings.get()`, `settings.update()` API methods
- [api.ts](../../web/src/types/api.ts) - `UserSettings` type
- [icons.ts](../../web/src/utils/icons.ts) - `SETTINGS_ICON`
- [popups.css](../../web/src/styles/components/popups.css) - Styles

### Testing

- **Backend integration tests**: [test_routes_settings.py](../../tests/integration/test_routes_settings.py)
- **E2E tests**: [settings.spec.ts](../../web/tests/e2e/settings.spec.ts)
- **Visual tests**: [popups.visual.ts](../../web/tests/visual/popups.visual.ts) - `popup-settings.png`, `popup-settings-empty.png`, `popup-settings-warning.png`

---

## Anonymous Mode

Anonymous mode allows users to chat without memory retrieval/storage, without reading past
conversations, and without integration tools (Todoist, Google Calendar).

### How It Works

1. **UI Toggle**: incognito icon button in the input toolbar (rightmost position)
2. **Per-conversation state**: stored in the Zustand store *and* persisted to the
   `conversations.anonymous_mode` column
3. **Survives reload**: the flag is read back when the conversation loads. It used to be
   runtime-only, so a conversation the user had marked private silently became
   memory-enabled after a refresh.
4. **Default OFF**: new conversations start with anonymous mode disabled

### What Anonymous Mode Disables

- **Memory retrieval**: user memories are not injected into the system prompt
- **Memory writes**: `manage_memory` is not bound, so no write can be attempted
- **Conversation search**: `search_conversations` / `read_conversation` are not bound -
  otherwise a "private" chat could pull back the history the user stepped away from
- **Integration tools**: Todoist and Google Calendar are excluded
- **Integration documentation**: the system prompt omits Todoist/Calendar docs (the LLM
  does not even know these tools exist)

### Key Implementation Details

**Frontend:**
- `anonymousModeByConversation: Map<string, boolean>` in [store.ts](../../web/src/state/store.ts)
- Toggle in [toolbar.ts](../../web/src/core/toolbar.ts); persists via
  `conversations.setAnonymousMode()` and is adopted on load in [conversation.ts](../../web/src/core/conversation.ts)
- State migrates from temp ID to permanent ID when a conversation is first persisted

**Backend:**
- `conversations.anonymous_mode` column ([migration 0047](../../migrations/0047_add_conversation_anonymous_mode.py))
- `PATCH /api/conversations/<id>/anonymous-mode` persists the toggle
- [routes/chat.py](../../src/api/routes/chat.py) ORs the stored flag with the request flag,
  so a stale client cannot un-anonymise a conversation and a brand-new conversation can be
  anonymous before the toggle is persisted
- `_ANONYMOUS_EXCLUDED_TOOLS` in [tools/__init__.py](../../src/agent/tools/__init__.py)
- `get_system_prompt(anonymous_mode=True)` skips memory injection and productivity docs

### Testing

- **Backend unit tests**: `TestGetToolsForRequest` in [test_tools.py](../../tests/unit/test_tools.py),
  `TestGetSystemPromptAnonymousMode` in [test_chat_agent_helpers.py](../../tests/unit/test_chat_agent_helpers.py)
- **Route tests**: `TestAnonymousMode` in [test_routes_conversations.py](../../tests/integration/test_routes_conversations.py)
- **E2E tests**: "Chat - Anonymous Mode" describe block in [chat.spec.ts](../../web/tests/e2e/chat.spec.ts)
- Includes regression test for the temp-to-permanent ID transition bug

## See Also

- [Integrations](integrations.md) - Todoist and Google Calendar tools disabled in anonymous mode
- [Chat and Streaming](chat-and-streaming.md) - System prompt construction
- [Testing Guide](../testing.md) - Testing patterns for memory and context features
