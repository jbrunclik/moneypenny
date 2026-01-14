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
3. **System prompt injection**: `get_user_context()` in chat_agent.py builds the context section
4. **Prompt integration**: `get_system_prompt()` includes the user context when building the system prompt

### Key Files

- [config.py](../../src/config.py) - `USER_LOCATION` configuration
- [chat_agent.py](../../src/agent/chat_agent.py) - `get_user_context()`, `get_system_prompt()` with `user_name` parameter
- [routes/chat.py](../../src/api/routes/chat.py) - Passes `user_name` from authenticated user to chat methods

---

## User Memory

The LLM can learn and remember interesting facts about the user across conversations for personalization.

### Design Decisions

- **Delete only**: Users can view and delete memories, but not edit them (prevents fake memories)
- **100 memory limit**: With LLM-managed rotation when near limit
- **LLM deduplication**: LLM sees existing memories and decides to update/consolidate/remove
- **Categories**: `preference`, `fact`, `context`, `goal`

### How It Works

1. **Injection**: Current memories are injected into the system prompt with timestamps and IDs
2. **Extraction**: LLM includes memory operations in a metadata block at the end of responses
3. **Processing**: Backend processes operations (add/update/delete) after response completion
4. **Management**: Users can view/delete memories via brain icon button in sidebar

### Memory Operations Format

The LLM includes memory operations in the metadata block:
```json
{
  "memory_operations": [
    {"action": "add", "content": "User prefers dark mode", "category": "preference"},
    {"action": "update", "id": "mem-123", "content": "User now prefers light mode"},
    {"action": "delete", "id": "mem-456"}
  ]
}
```

### Key Files

**Backend:**
- [migrations/0009_add_user_memories.py](../../migrations/0009_add_user_memories.py) - Database migration
- [models/](../../src/db/models/) - `Memory` dataclass, CRUD methods
- [chat_agent.py](../../src/agent/chat_agent.py) - `MEMORY_SYSTEM_PROMPT`, `get_user_memories_prompt()`
- [utils.py](../../src/api/utils.py) - `extract_memory_operations()` for parsing metadata
- [routes/chat.py](../../src/api/routes/chat.py) - Memory processing in chat endpoints
- [routes/memory.py](../../src/api/routes/memory.py) - Memory API endpoints
- [config.py](../../src/config.py) - `USER_MEMORY_LIMIT` constant (default: 100)

**Frontend:**
- [MemoriesPopup.ts](../../web/src/components/MemoriesPopup.ts) - Popup component with category badges, delete confirmation
- [Sidebar.ts](../../web/src/components/Sidebar.ts) - Brain icon button trigger
- [client.ts](../../web/src/api/client.ts) - `memories.list()`, `memories.delete()` API methods
- [api.ts](../../web/src/types/api.ts) - `Memory`, `MemoriesResponse` types
- [icons.ts](../../web/src/utils/icons.ts) - `BRAIN_ICON`
- [popups.css](../../web/src/styles/components/popups.css) - Styles

### Testing

- **Backend integration tests**: [test_routes_memories.py](../../tests/integration/test_routes_memories.py)
- **Visual tests**: [popups.visual.ts](../../web/tests/visual/popups.visual.ts) - `popup-memories.png`, `popup-memories-empty.png`, `mobile-popup-memories.png`

### Memory Defragmentation

A nightly systemd timer consolidates and cleans up user memories using an LLM to keep memory banks efficient.

**When it runs:**
- Nightly at 3:30 AM (with up to 30 min random delay)
- Only processes users with >= 50 memories (configurable via `MEMORY_DEFRAG_THRESHOLD`)
- Uses the advanced model (`gemini-3-pro-preview` by default) for quality consolidation

**What it does:**
1. **Merges related memories**: Combines memories about the same topic into one
2. **Removes duplicates**: Deletes memories that say essentially the same thing
3. **Updates outdated info**: Keeps newer information when there's a contradiction
4. **Removes irrelevant memories**: Cleans up vague or temporary memories
5. **Preserves important facts**: Never deletes family info, identity facts, strong preferences

**Manual execution:**
```bash
make defrag-memories              # Run defragmentation
make defrag-memories -- --dry-run # Preview changes without applying
```

**Configuration:**
```bash
# .env
MEMORY_DEFRAG_THRESHOLD=50        # Only defrag users with >= this many memories
MEMORY_DEFRAG_MODEL=gemini-3-pro-preview  # LLM model to use
```

**Key files:**
- [defragment_memories.py](../../scripts/defragment_memories.py) - Main defragmentation script
- [ai-chatbot-memory-defrag.service](../../systemd/ai-chatbot-memory-defrag.service) - Systemd service
- [ai-chatbot-memory-defrag.timer](../../systemd/ai-chatbot-memory-defrag.timer) - Nightly timer
- [config.py](../../src/config.py) - Configuration constants
- [models/](../../src/db/models/) - `get_users_with_memory_counts()`, `bulk_update_memories()`

**Testing:**
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
- [chat_agent.py](../../src/agent/chat_agent.py) - `CUSTOM_INSTRUCTIONS_PROMPT` constant, `get_system_prompt()` with `custom_instructions` parameter
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

Anonymous mode allows users to chat without memory retrieval/storage and without integration tools (Todoist, Google Calendar).

### How It Works

1. **UI Toggle**: Incognito icon button in the input toolbar (rightmost position)
2. **Per-conversation state**: Anonymous mode is stored per-conversation in Zustand store (`anonymousModeByConversation: Map`)
3. **Runtime only**: Not persisted to DB - resets on page refresh
4. **Default OFF**: New conversations start with anonymous mode disabled

### What Anonymous Mode Disables

- **Memory retrieval**: User memories are not injected into the system prompt
- **Memory storage**: Memory operations from LLM responses are ignored
- **Integration tools**: Todoist and Google Calendar tools are excluded from the LLM's available tools
- **Integration documentation**: System prompt excludes Todoist/Calendar documentation (the LLM doesn't even know these tools exist)

### Key Implementation Details

**Frontend:**
- `anonymousModeByConversation: Map<string, boolean>` in [store.ts](../../web/src/state/store.ts)
- Toggle button state in [main.ts](../../web/src/main.ts) via `initToolbarButtons()` and `updateAnonymousButtonState()`
- `INCOGNITO_ICON` in [icons.ts](../../web/src/utils/icons.ts)
- State migrates from temp ID to permanent ID when conversation is first persisted

**Backend:**
- `anonymous_mode` field in `ChatRequest` schema ([schemas.py](../../src/api/schemas.py))
- `get_tools_for_request(anonymous_mode)` in [tools/__init__.py](../../src/agent/tools/__init__.py) filters integration tools
- `ChatAgent.__init__()` passes filtered tools to graph creation
- `get_system_prompt(anonymous_mode=True)` skips memory injection and excludes `TOOLS_SYSTEM_PROMPT_PRODUCTIVITY` (Todoist/Calendar docs)
- Memory operations skipped in [routes/chat.py](../../src/api/routes/chat.py) when `anonymous_mode=True`

### Testing

- **Backend unit tests**:
  - `TestGetToolsForRequest` in [test_tools.py](../../tests/unit/test_tools.py)
  - `TestGetSystemPromptAnonymousMode` in [test_chat_agent_helpers.py](../../tests/unit/test_chat_agent_helpers.py)
- **E2E tests**: "Chat - Anonymous Mode" describe block in [chat.spec.ts](../../web/tests/e2e/chat.spec.ts)
- Includes regression test for temp-to-permanent ID transition bug

## See Also

- [Integrations](integrations.md) - Todoist and Google Calendar tools disabled in anonymous mode
- [Chat and Streaming](chat-and-streaming.md) - System prompt construction
- [Testing Guide](../testing.md) - Testing patterns for memory and context features
