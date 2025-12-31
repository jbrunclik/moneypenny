# AI Chatbot - Claude Context

This file contains context for Claude Code to work effectively on this project.

## Quick Reference

- **Dev**: `make dev` (runs Flask + Vite concurrently)
- **Build**: `make build` (production build)
- **Lint**: `make lint` (ruff + mypy + eslint)
- **Test**: `make test` (run all tests)
- **Setup**: `make setup` (venv + deps)
- **Help**: `make` (show all targets)

## Project Structure

```
ai-chatbot/
├── src/                          # Flask backend
│   ├── app.py                    # Flask entry point, Vite manifest loading
│   ├── config.py                 # Environment config
│   ├── templates/
│   │   └── index.html            # Jinja2 shell (meta tags, asset injection)
│   ├── auth/
│   │   ├── jwt_auth.py           # JWT token handling, @require_auth decorator
│   │   └── google_auth.py        # GIS token validation, email whitelist
│   ├── api/
│   │   ├── routes.py             # REST endpoints (/api/*, /auth/*)
│   │   ├── schemas.py            # Pydantic request validation schemas
│   │   ├── validation.py         # @validate_request decorator
│   │   ├── errors.py             # Standardized error responses
│   │   └── utils.py              # API response building utilities
│   ├── agent/
│   │   ├── chat_agent.py         # LangGraph agent with Gemini
│   │   └── tools.py              # Agent tools (fetch_url, web_search, generate_image, execute_code)
│   ├── db/
│   │   └── models.py             # SQLite: User, Conversation, Message
│   └── utils/
│       └── images.py             # Thumbnail generation (Pillow)
├── web/                          # Vite + TypeScript frontend
│   ├── vite.config.ts            # Vite config with Flask proxy
│   ├── tsconfig.json             # TypeScript config
│   ├── package.json              # Frontend dependencies
│   └── src/
│       ├── main.ts               # Entry point, app shell, event wiring
│       ├── types/                # TypeScript interfaces
│       │   ├── api.ts            # API response types
│       │   └── google.d.ts       # Google Identity Services types
│       ├── api/client.ts         # Typed fetch wrapper, streaming
│       ├── auth/google.ts        # Google Sign-In, JWT handling
│       ├── state/store.ts        # Zustand store
│       ├── components/           # UI modules
│       │   ├── Sidebar.ts        # Conversation list
│       │   ├── Messages.ts       # Message rendering
│       │   ├── MessageInput.ts   # Input area, file preview
│       │   ├── ModelSelector.ts  # Model dropdown
│       │   ├── FileUpload.ts     # File handling, base64
│       │   ├── VoiceInput.ts     # Speech-to-text input
│       │   ├── ThinkingIndicator.ts # Thinking/tool status during streaming
│       │   ├── Lightbox.ts       # Image viewer
│       │   ├── ScrollToBottom.ts # Scroll-to-bottom button
│       │   ├── VersionBanner.ts  # New version notification
│       │   ├── Toast.ts          # Toast notifications
│       │   ├── Modal.ts          # Modal dialogs (alert/confirm/prompt)
│       │   └── SettingsPopup.ts  # User settings (custom instructions)
│       ├── gestures/swipe.ts     # Touch handlers
│       ├── utils/
│       │   ├── dom.ts            # DOM helpers, escapeHtml
│       │   ├── markdown.ts       # marked + highlight.js, table scroll wrapper
│       │   ├── thumbnails.ts     # Intersection Observer lazy loading
│       │   ├── icons.ts          # SVG icon constants
│       │   └── logger.ts         # Structured logging utility
│       └── styles/               # CSS files (modular structure)
│           ├── main.css          # Entry point, imports all modules
│           ├── variables.css     # Design system tokens
│           ├── base.css          # Reset, typography, utilities
│           ├── layout.css        # App shell structure
│           └── components/       # Component-specific styles
│               ├── buttons.css
│               ├── messages.css
│               ├── sidebar.css
│               ├── input.css
│               ├── popups.css
│               └── thinking.css
└── static/                       # Build output + PWA assets
    ├── assets/                   # Vite output (hashed JS/CSS)
    ├── manifest.json
    └── icons/
```

## Key Files

- [config.py](src/config.py) - All env vars, model definitions
- [routes.py](src/api/routes.py) - API endpoints
- [schemas.py](src/api/schemas.py) - Pydantic request validation schemas
- [validation.py](src/api/validation.py) - Request validation decorator
- [chat_agent.py](src/agent/chat_agent.py) - LangGraph graph, Gemini integration
- [models.py](src/db/models.py) - Database schema and operations
- [images.py](src/utils/images.py) - Thumbnail generation for uploaded images
- [main.ts](web/src/main.ts) - Frontend entry point
- [store.ts](web/src/state/store.ts) - Zustand state management

## Development Workflow

### Local Development
```bash
make dev  # Runs Flask (8000) + Vite (5173) concurrently
```
- Vite dev server proxies API calls to Flask
- HMR enabled for instant CSS/JS updates
- TypeScript type checking on save

### Production Build
```bash
make build  # Outputs to static/assets/
```
- Vite generates hashed filenames for cache busting
- Flask reads manifest.json to inject correct asset paths

### Deployment (Hetzner)
systemd runs `npm install && npm run build` via ExecStartPre before starting gunicorn.

## Gemini API Notes

### Models
- `gemini-3-pro-preview` - Complex tasks, advanced reasoning
- `gemini-3-flash-preview` - Fast, cheap (default)

### Response Format
Gemini may return content in various formats:
- String: `"response text"`
- List: `[{'type': 'text', 'text': '...', 'extras': {...}}]`
- Dict: `{'type': 'text', 'text': '...'}`

Use `extract_text_content()` in [chat_agent.py](src/agent/chat_agent.py) to normalize.

### Parameters
- `thinking_level`: Controls reasoning (minimal/low/medium/high)
- Temperature: Keep at 1.0 (Gemini 3 default)

## Auth Flow

Uses Google Identity Services (GIS) for client-side authentication:

1. `FLASK_ENV=development` → Skip all auth, use "local@localhost" user
2. Otherwise:
   - Frontend loads GIS library and renders "Sign in with Google" button
   - User clicks → Google popup → Returns ID token to frontend
   - Frontend sends token to `POST /auth/google`
   - Backend validates token via Google's tokeninfo endpoint
   - Backend checks email whitelist, returns JWT
   - Frontend stores JWT for subsequent API calls
   - Frontend schedules automatic token refresh before expiration

### JWT Token Handling

**Token lifecycle:**
- Tokens expire after 7 days (`JWT_EXPIRATION_SECONDS = SECONDS_PER_WEEK`)
- Frontend automatically refreshes tokens when less than 2 days remain
- This 48-hour window ensures users can skip a day without getting logged out
- On page load, `checkAuth()` validates the token and schedules refresh
- Token refresh uses `POST /auth/refresh` endpoint

**Token security:**
- In production, `JWT_SECRET_KEY` must be at least 32 characters
- Config validation fails startup if secret is too short

**Error codes:**
The backend returns distinct error codes for authentication failures:
- `AUTH_REQUIRED` (401): No token provided
- `AUTH_EXPIRED` (401): Token has expired → prompts user to re-login
- `AUTH_INVALID` (401): Token is malformed or signature is invalid
- `AUTH_FORBIDDEN` (403): Valid auth but not authorized for resource

**Frontend error handling:**
- `ApiError.isTokenExpired`: True when backend returns `AUTH_EXPIRED`
- `ApiError.isAuthError`: True for any 401 or auth-related error code
- On token expiration, user sees a toast: "Your session has expired. Please sign in again."

**Key files:**
- [jwt_auth.py](src/auth/jwt_auth.py) - Token creation, validation, `decode_token_with_status()`
- [google.ts](web/src/auth/google.ts) - `scheduleTokenRefresh()`, `checkAuth()`, `performTokenRefresh()`
- [client.ts](web/src/api/client.ts) - `ApiError` with `isTokenExpired` and `isAuthError` properties
- [routes.py](src/api/routes.py) - `/auth/refresh` endpoint

## Code Style

- Type hints in all Python code
- TypeScript for all frontend code (strict mode)
- Conventional Commits: `type(scope): description`
  - Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`
- **Test all UI changes on both desktop and mobile** - The app has a responsive layout with different behavior at 768px breakpoint. Always verify changes work on both layouts.

### Constants and Configuration

Magic numbers and configurable values are centralized in dedicated files:

**Frontend:**
- [constants.ts](web/src/constants.ts) - True constants only (unit conversions like `MS_PER_SECOND`, `BYTES_PER_MB`)
- [config.ts](web/src/config.ts) - Developer-configurable values (timeouts, thresholds, UI settings)

**Backend:**
- [constants.py](src/constants.py) - True constants only (unit conversions like `SECONDS_PER_MINUTE`, `BYTES_PER_MB`)
- [config.py](src/config.py) - Developer-configurable values (timeouts, limits, feature settings)

**Guidelines for adding new values:**

1. **Constants vs Config:**
   - `constants.{ts,py}`: Only mathematical/unit constants that will never change (e.g., `MS_PER_SECOND = 1000`)
   - `config.{ts,py}`: Values that a developer might want to tweak (timeouts, thresholds, limits)

2. **Naming conventions:**
   - Use `SCREAMING_SNAKE_CASE` for all constants/config
   - Include units in the name: `_MS`, `_SECONDS`, `_PX`, `_BYTES`
   - Example: `API_TIMEOUT_MS`, `SWIPE_THRESHOLD_PX`, `MAX_FILE_SIZE_BYTES`

3. **Use base constants when defining derived values:**
   ```typescript
   // Good - uses base constant
   export const API_TIMEOUT_MS = 30 * MS_PER_SECOND;

   // Bad - magic number
   export const API_TIMEOUT_MS = 30000;
   ```

4. **When NOT to extract:**
   - Test files (hardcoded timeouts in tests are fine)
   - Obvious values like `0`, `1`, `-1`
   - Array indices
   - Loop bounds that are clearly tied to the data structure

5. **Must match between FE/BE:**
   - `DEFAULT_CONVERSATION_TITLE` must be identical in both config files
   - Any shared constants should be documented with a comment noting they must match

### Code Quality Guidelines

Follow these principles to maintain clean, testable code:

**1. Keep Functions Small and Focused**
- Each function should do ONE thing well
- If a function exceeds ~50 lines, consider splitting it
- Use descriptive names that explain what the function does, not how it does it
- Extract complex logic into helper functions with clear inputs/outputs

**2. Organize Large Files with Sections**
When a module has multiple distinct areas of functionality:
```python
# ============================================================================
# Section Name (e.g., "Helper Functions", "API Endpoints")
# ============================================================================

def some_function():
    ...
```

**3. Extract Testable Units**
- Logic that can be tested independently should be in its own function
- Helper functions should be pure where possible (same input → same output)
- Avoid mixing I/O operations with business logic
- Complex conditionals should become named functions

**4. Function Naming Patterns**
```python
# Prefix private helpers with underscore
def _parse_output_files(stdout: str) -> list[str]:
    """Parse and return..."""

# Use verb_noun pattern for actions
def extract_files_from_sandbox(session, filenames):
    """Extract files from..."""

# Use is_/has_/can_ for boolean helpers
def _needs_font_setup(code: str) -> bool:
    """Check if code needs..."""
```

**5. When to Refactor**
Extract helper functions when you see:
- Deeply nested code (>3 levels of indentation)
- Repeated logic patterns
- Long functions that do multiple things
- Code that's hard to unit test
- Comments explaining what the next block does (make it a function instead)

**6. Example: Before and After**
```python
# BEFORE: Long function doing multiple things
def execute_code(code: str) -> str:
    # 200 lines of: wrapping, execution, file extraction, response building
    ...

# AFTER: Orchestrator that calls focused helpers
def execute_code(code: str) -> str:
    wrapped_code = _wrap_user_code(code)
    result = _run_in_sandbox(wrapped_code)
    files, clean_stdout = _parse_output_files(result.stdout)
    full_files, metadata = _extract_output_files(session, files)
    return _build_execution_response(result, clean_stdout, metadata, full_files)
```

**7. File Organization**
- Group related functionality together
- Consider splitting large files (>500 lines) into modules
- Keep imports organized: stdlib, third-party, local (separated by blank lines)
- Put helper functions near the functions that use them

## Pre-Commit Checklist

**Before committing any changes, you MUST run:**

```bash
make lint   # Run all linters (ruff, mypy, eslint)
make test   # Run all tests
```

Both commands must pass without errors. If linting fails, run `make lint-fix` to auto-fix issues where possible.

**When implementing new features:**
- Add tests for new backend code to maintain coverage
- Place unit tests in `tests/unit/` and integration tests in `tests/integration/`
- Use existing fixtures from `tests/conftest.py` where applicable
- Mock all external services (never make real API calls in tests)

**When fixing bugs (TDD approach):**
1. **Write a failing test first** that reproduces the bug
2. Run the test to confirm it fails (captures the regression)
3. Implement the fix
4. Run the test to confirm it passes
5. Run the full test suite to ensure no regressions

This approach ensures:
- The bug is documented as a test case
- The fix is verified to work
- The bug won't regress in the future

## Input Toolbar

The input area has a toolbar row above the textarea with controls:

```
[Model dropdown] [Stream] [Search]              [Mic] [Attach]
┌────────────────────────────────────────────────────────────┐
│ Textarea                                          [Send]   │
└────────────────────────────────────────────────────────────┘
```

- **Model selector**: Dropdown to switch between Gemini models
- **Stream toggle**: Enable/disable streaming responses (persisted to localStorage)
- **Search toggle**: One-shot button to force `web_search` tool for the next message only
- **Mic**: Voice input (see Voice Input section below)
- **Attach**: File upload

### Message Sending Behavior

The Enter key behavior differs between desktop and mobile viewports:

- **Desktop** (viewport > 768px): Enter sends the message, Shift+Enter adds a newline
- **Mobile** (viewport ≤ 768px): Enter always adds a newline, users must tap the Send button

This allows mobile users to easily add multiple lines to their prompts (since there's no easy way to type Shift+Enter on mobile keyboards), while preserving the convenient Enter-to-send behavior on desktop.

**Implementation:**
- `isMobileViewport()` in [MessageInput.ts](web/src/components/MessageInput.ts) checks `window.innerWidth` against `MOBILE_BREAKPOINT_PX`
- The keydown handler only sends on Enter when NOT in mobile viewport
- `MOBILE_BREAKPOINT_PX` (768px) is defined in [config.ts](web/src/config.ts) and matches the CSS media query breakpoint in [layout.css](web/src/styles/layout.css)

### Force Tools System

The `forceTools` state in Zustand allows forcing specific tools to be used. Currently only `web_search` is exposed via UI, but the system supports any tool name. The force tools instruction is added to the system prompt when tools are specified.

- Frontend: `store.forceTools: string[]` with `toggleForceTool(tool)` and `clearForceTools()`
- Backend: `force_tools` parameter in `/chat/batch` and `/chat/stream` endpoints
- Agent: `get_force_tools_prompt()` in [chat_agent.py](src/agent/chat_agent.py)

### Clipboard Paste

Users can paste screenshots directly from the clipboard into the message input (Cmd+V / Ctrl+V).

**How it works:**
1. A `paste` event listener on the textarea detects clipboard content
2. If clipboard contains image files, they're extracted and processed
3. Images are renamed with timestamp-based names (`screenshot-YYYY-MM-DDTHH-MM-SS.png`)
4. Uses the existing `addFilesToPending()` flow for validation and preview
5. Text paste is handled normally by the browser (not intercepted)

**Supported formats:**
- PNG, JPEG, GIF, WebP images
- Works with screenshots (Cmd+Shift+4 on Mac, PrtScn on Windows)
- Works with copied images from other applications

**Implementation details:**
- `handlePaste()` in [MessageInput.ts](web/src/components/MessageInput.ts) handles the paste event
- Only images are processed; non-image files and text are passed through
- `preventDefault()` is only called when images are present (to avoid interfering with text paste)
- `addFilesToPending()` in [FileUpload.ts](web/src/components/FileUpload.ts) handles validation and base64 conversion

**Key files:**
- [MessageInput.ts](web/src/components/MessageInput.ts) - `handlePaste()` function
- [FileUpload.ts](web/src/components/FileUpload.ts) - `addFilesToPending()` for file processing

**Testing:**
- Unit tests: `handlePaste` describe block in [message-input.test.ts](web/tests/unit/message-input.test.ts)
- E2E tests: "Chat - Clipboard Paste" describe block in [chat.spec.ts](web/tests/e2e/chat.spec.ts)

## Web Search Sources

When the LLM uses `web_search` or `fetch_url` tools, it cites sources that are displayed to the user.

### How it works
1. **Tool returns JSON**: `web_search` returns `{"query": "...", "results": [{title, url, snippet}, ...]}` instead of plain text
2. **LLM appends metadata**: System prompt instructs LLM to append `<!-- METADATA:\n{"sources": [...]}\n-->` at the end of responses when web tools are used
3. **Backend extracts sources**: `extract_metadata_from_response()` in [chat_agent.py](src/agent/chat_agent.py) parses and strips the metadata block. It handles both HTML comment format (preferred) and plain JSON format (fallback), removing both if the LLM outputs metadata in both formats
4. **Streaming filters metadata**: During streaming, the HTML comment metadata marker is detected and not sent to the frontend. Any plain JSON metadata that slips through is cleaned in the final buffer check
5. **Sources stored in DB**: Messages table has a `sources` column (JSON array)
6. **Sources in API response**: Both batch and streaming responses include `sources` array
7. **UI shows sources button**: A globe icon appears in message actions when sources exist, opening a popup with clickable links

### Key files
- [tools.py](src/agent/tools.py) - `web_search()` returns structured JSON
- [chat_agent.py](src/agent/chat_agent.py) - `TOOLS_SYSTEM_PROMPT`, `extract_metadata_from_response()`, streaming filter
- [models.py](src/db/models.py) - `Message.sources` field, `add_message()` with sources param
- [routes.py](src/api/routes.py) - Sources included in batch/stream responses
- [SourcesPopup.ts](web/src/components/SourcesPopup.ts) - Popup component
- [Messages.ts](web/src/components/Messages.ts) - Sources button rendering

### Metadata format
```
<!-- METADATA:
{"sources": [{"title": "Source Title", "url": "https://..."}]}
-->
```

The metadata block is always at the end of the LLM response and is stripped before storing/displaying content. Sometimes the LLM outputs plain JSON metadata (without HTML comments) instead of or in addition to the HTML comment format. The extraction function handles both formats, preferring HTML comment format but removing both if present.

## Image Generation

The app can generate images using Gemini's image generation model (`gemini-3-pro-image-preview`).

### How it works
1. **Tool available**: `generate_image(prompt, aspect_ratio)` tool in [tools.py](src/agent/tools.py)
2. **Tool returns JSON**: Returns `{"prompt": "...", "image": {"data": "base64...", "mime_type": "image/png"}}`
3. **LLM appends metadata**: System prompt instructs LLM to include `"generated_images": [{"prompt": "..."}]` in the metadata block
4. **Backend extracts images**: `extract_generated_images_from_tool_results()` in [routes.py](src/api/routes.py) parses tool results
5. **Images stored as files**: Generated images are stored as file attachments on the message
6. **Metadata stored in DB**: Messages table has a `generated_images` column (JSON array)
7. **UI shows sparkles button**: A sparkles icon appears in message actions when generated images exist, opening a popup showing the prompt used and the cost of image generation (excluding prompt tokens)

### Key files
- [tools.py](src/agent/tools.py) - `generate_image()` tool using google-genai SDK
- [chat_agent.py](src/agent/chat_agent.py) - System prompt with metadata instructions, tool result capture during streaming
- [models.py](src/db/models.py) - `Message.generated_images` field
- [routes.py](src/api/routes.py) - Image extraction from tool results, API responses
- [ImageGenPopup.ts](web/src/components/ImageGenPopup.ts) - Popup showing generation info
- [InfoPopup.ts](web/src/components/InfoPopup.ts) - Generic popup component used by both sources and image gen
- [Messages.ts](web/src/components/Messages.ts) - Sparkles button rendering

### Metadata format
The metadata block supports both sources and generated_images:
```
<!-- METADATA:
{"sources": [...], "generated_images": [{"prompt": "..."}]}
-->
```

### Aspect ratios
Supported: `1:1` (default), `16:9`, `9:16`, `4:3`, `3:4`, `3:2`, `2:3`

### Tool result handling
Tool results (including generated images) are returned from both `chat_batch()` and `stream_chat()` methods but are **not persisted** to the database. This is intentional:
1. **Prevents state bloat**: Generated images are large base64 blobs that would grow the state rapidly
2. **Ensures fresh tool calls**: If tool results were persisted, the LLM might skip calling `generate_image` for follow-up requests, thinking the tool was already called
3. **Conversation context is sufficient**: The human/AI message history stored in the `messages` table provides enough context for multi-turn conversations

The `chat_batch()` method returns `(response_text, tool_results, usage_info)`. The batch and streaming endpoints extract images from `tool_results` for storage, then discard the tool results themselves.

## Code Execution Sandbox

The app can execute Python code in a secure Docker sandbox using [llm-sandbox](https://github.com/vndee/llm-sandbox).

### How it works
1. **Tool available**: `execute_code(code)` tool in [tools.py](src/agent/tools.py)
2. **Docker sandbox**: Code runs in an isolated container with no network access
3. **File output**: Code saves files to `/output/` directory, which are extracted and returned
4. **Automatic plots**: Matplotlib plots are captured automatically via llm-sandbox
5. **Pre-installed libraries**: numpy, pandas, matplotlib, scipy, sympy, pillow, reportlab, fpdf2

### Security constraints
- **No network**: Containers run with `--network none` (default in llm-sandbox)
- **No host access**: Code cannot access files outside the container
- **Resource limits**: Configurable timeout (30s default), memory limit (512MB default)
- **Fresh container**: Each execution creates a new container, destroyed after use

### Configuration
```bash
CODE_SANDBOX_ENABLED=true           # Enable/disable (default: true)
CODE_SANDBOX_TIMEOUT=30             # Execution timeout in seconds
CODE_SANDBOX_MEMORY_LIMIT=512m      # Container memory limit
CODE_SANDBOX_LIBRARIES=numpy,pandas,matplotlib,scipy,sympy,pillow,reportlab,fpdf2
```

### File output pattern (uses `_full_result` to save tokens)
The tool uses the same `_full_result` pattern as `generate_image` to avoid sending large file data back to the LLM:

1. **Wrapped execution**: User code is wrapped to create `/output/` directory and list files after execution
2. **File extraction**: Files are extracted via `session.copy_from_runtime()` to temp files
3. **LLM sees metadata only**: Response includes file metadata (name, type, size) but NOT the base64 data
4. **Full data in `_full_result`**: Actual file data is stored in `_full_result.files` for server-side extraction
5. **Server extracts files**: `extract_code_output_files_from_tool_results()` extracts files from `_full_result`
6. **Stored as attachments**: Files are attached to the assistant message like any other file upload

**Token optimization:**
- Without this pattern: Each 100KB file would add ~130K tokens to the next request
- With this pattern: LLM only sees ~50 tokens of metadata per file

**Implementation details:**
- [tools.py](src/agent/tools.py) - `execute_code()` puts files in `_full_result.files`
- [images.py](src/utils/images.py) - `extract_code_output_files_from_tool_results()` extracts files
- [routes.py](src/api/routes.py) - Combines code output files with generated images before saving message

### Example use cases
- Mathematical calculations (sympy for symbolic math)
- Data analysis (pandas, numpy)
- Charts and visualizations (matplotlib)
- PDF document generation (reportlab)
- JSON/CSV data transformation

### Graceful degradation
- If Docker is not available, the tool returns an error message
- Docker availability is checked once and cached
- The tool is only added to the available tools list if `CODE_SANDBOX_ENABLED=true`

### Key files
- [tools.py](src/agent/tools.py) - `execute_code()` tool, `is_code_sandbox_available()`, `_check_docker_available()`
- [images.py](src/utils/images.py) - `extract_code_output_files_from_tool_results()` for file extraction
- [config.py](src/config.py) - `CODE_SANDBOX_*` configuration options
- [chat_agent.py](src/agent/chat_agent.py) - System prompt with code execution instructions
- [routes.py](src/api/routes.py) - Extracts and attaches code output files to messages

### Testing locally
```bash
# Ensure Docker is running
docker info

# Test the sandbox manually
python -c "
from llm_sandbox import SandboxSession
with SandboxSession(lang='python') as s:
    result = s.run('print(1+1)')
    print(result.stdout)
"
```

## Stop Streaming

Users can abort an ongoing streaming response by clicking the stop button.

### How it works

1. **Button transformation**: When streaming starts for the current conversation, the send button transforms to a stop button (red square icon with `.btn-stop` class)
2. **State tracking**: `streamingConversationId` in Zustand store tracks which conversation is streaming
3. **Abort mechanism**: Clicking stop calls `abortController.abort()` on the streaming fetch request
4. **Stream cancellation**: The API client catches `AbortError` and re-throws it so the caller can handle cleanup
5. **UI cleanup**: The streaming assistant message element is removed from the DOM immediately
6. **User feedback**: A toast notification confirms "Response stopped."

**Note on partial messages**: When the user aborts, the backend cleanup thread may still save a partial message to the database. These partial messages are intentionally NOT deleted automatically - users can clean them up later using the message delete button (see TODO.md for planned feature). This simpler approach avoids complex timing issues with backend cleanup threads and race conditions.

### Key files

- [store.ts](web/src/state/store.ts) - `streamingConversationId` state and `setStreamingConversation()` action
- [client.ts](web/src/api/client.ts) - `stream()` method accepts optional `AbortController`, re-throws `AbortError` for caller handling
- [MessageInput.ts](web/src/components/MessageInput.ts) - Button transformation logic, subscribes to streaming state with `fireImmediately: true`
- [main.ts](web/src/main.ts) - `abortStreamingRequest()`, `handleStopStreaming()`, abort handling in `sendStreamingMessage()`
- [buttons.css](web/src/styles/components/buttons.css) - `.btn-stop` styles (red background)
- [icons.ts](web/src/utils/icons.ts) - `STOP_ICON` SVG constant (square icon)

### Race conditions handled

| Condition | Handling |
|-----------|----------|
| Stop clicked while done event processing | Done event clears streaming state; stop button disappears before click possible |
| User switches conversations during streaming | Stop button only shows for current streaming conversation |
| Rapid stop/send clicks | Button state controlled by store subscription; mode check in click handler |
| Stream naturally completes | `setStreamingConversation(null)` in finally block reverts button |
| Multiple conversations streaming in background | Only `streamingConversationId === currentConversation.id` shows stop button |

### Testing

- E2E tests: "Chat - Stop Streaming" describe block in [chat.spec.ts](web/tests/e2e/chat.spec.ts)

## Thinking Indicator

During streaming responses, the app shows a thinking indicator at the top of assistant messages to provide feedback about the model's internal processing and tool usage.

### Design Principles
- **Streaming only**: The indicator only appears during streaming mode, not when loading historical messages
- **No persistence**: Thinking state and tool activity are NOT stored in the database
- **Singleton thinking**: There's exactly ONE thinking item that accumulates all thinking text, updated in real-time
- **Live updates**: Thinking text is visible and updates during streaming, not just in finalized view
- **Full trace**: Shows thinking (singleton) + all tool events with details
- **Rich details**: Shows full thinking text, search queries, URLs, and image prompts
- **Auto-collapse**: When the message finishes, the indicator collapses into a "Show details" toggle

### How it works
1. **Backend streaming**: `stream_chat_events()` in [chat_agent.py](src/agent/chat_agent.py) yields structured events:
   - `{"type": "thinking", "text": "..."}` - Accumulated thinking text (if `include_thoughts=True`)
   - `{"type": "tool_start", "tool": "web_search", "detail": "search query"}` - Tool starting with details
   - `{"type": "tool_end", "tool": "web_search"}` - When a tool finishes
   - `{"type": "token", "text": "..."}` - Regular content tokens
   - `{"type": "final", ...}` - Final result with metadata

2. **SSE forwarding**: [routes.py](src/api/routes.py) forwards these events via Server-Sent Events

3. **Frontend handling**: [main.ts](web/src/main.ts) parses events and calls:
   - `updateStreamingThinking(text)` for thinking events (with full accumulated text)
   - `updateStreamingToolStart(tool, detail)` for tool_start events (with optional detail)
   - `updateStreamingToolEnd()` for tool_end events

4. **UI rendering**: [ThinkingIndicator.ts](web/src/components/ThinkingIndicator.ts) manages the indicator:
   - Maintains a trace of all thinking/tool events with details
   - Shows animated "Thinking" with brain icon and dots during thinking
   - Shows tool icons, labels, and details (query/URL/prompt) with animated dots during execution
   - Shows checkmark when tools complete
   - Collapses into an expandable "Show details" toggle when message finishes

### Tool labels and details
The indicator uses user-friendly labels and shows relevant details for tools:
- `web_search` → "Searching the web" + search query → "Searched" + query (finalized)
- `fetch_url` → "Fetching page" + URL → "Fetched" + URL (finalized)
- `generate_image` → "Generating image" + prompt → "Generated image" + prompt (finalized)
- `execute_code` → "Running code" + first line of code → "Ran code" (finalized)

### Trace state management
The thinking state tracks a full trace of events:
```typescript
interface ThinkingTraceItem {
  type: 'thinking' | 'tool';
  label: string;
  detail?: string;  // thinking text, search query, URL, or prompt
  completed: boolean;
}
```

**Singleton thinking behavior:**
- The trace is initialized with ONE thinking item at index 0
- All thinking updates go to this same item (detail gets replaced, not appended)
- When a tool starts, thinking is marked `completed: true` but remains in place
- If more thinking comes after a tool, the same thinking item is updated and marked `completed: false`
- This ensures there's always exactly one thinking item showing accumulated/latest thinking text

**Example trace progression:**
1. Initial: `[{type: 'thinking', completed: false}]`
2. Thinking arrives: `[{type: 'thinking', detail: "Analyzing...", completed: false}]`
3. Tool starts: `[{type: 'thinking', detail: "Analyzing...", completed: true}, {type: 'tool', label: 'web_search', ...}]`
4. More thinking: `[{type: 'thinking', detail: "New analysis...", completed: false}, {type: 'tool', ...}]`

### Gemini thinking support
The Gemini API supports a `include_thoughts=True` parameter that returns thinking content in the response. When enabled:
- `ChatGoogleGenerativeAI` is initialized with `include_thoughts=True`
- Response chunks may contain parts with `{'type': 'thinking', 'thinking': "..."}` format
- `extract_thinking_and_text()` separates thinking content from regular text
- Thinking text is accumulated across chunks and emitted as updates
- The backend yields `{"type": "thinking", "text": accumulated_text}` events during streaming

### Key files
- [chat_agent.py](src/agent/chat_agent.py) - `stream_chat_events()`, `extract_thinking_and_text()`
- [routes.py](src/api/routes.py) - SSE streaming with thinking/tool events
- [api.ts](web/src/types/api.ts) - `StreamEvent` and `ThinkingState` types
- [ThinkingIndicator.ts](web/src/components/ThinkingIndicator.ts) - UI component
- [Messages.ts](web/src/components/Messages.ts) - `addStreamingMessage()`, streaming state management
- [main.ts](web/src/main.ts) - Event handling
- [thinking.css](web/src/styles/components/thinking.css) - Styles and animations

### Testing
- Backend unit tests: `TestExtractThinkingAndText` in [test_chat_agent_helpers.py](tests/unit/test_chat_agent_helpers.py)
- Frontend unit tests: [thinking-indicator.test.ts](web/tests/unit/thinking-indicator.test.ts)
- E2E tests: "Chat - Thinking Indicator" describe block in [chat.spec.ts](web/tests/e2e/chat.spec.ts)

### Streaming graceful degradation
The streaming implementation handles server restarts gracefully:
- LangGraph uses a `ThreadPoolExecutor` internally for graph execution
- During server restart, the executor shuts down while streaming may still be in progress
- This raises `RuntimeError: cannot schedule new futures after shutdown`
- The `stream_chat_events()` method catches this specific error and continues with accumulated content
- The final event is still yielded with whatever content was accumulated before the interruption
- This allows partial responses to be saved to the database even during restarts

## Voice Input

Voice input uses the Web Speech API (`SpeechRecognition`) in [VoiceInput.ts](web/src/components/VoiceInput.ts):

- **Chrome/Edge**: Uses Google's cloud servers (requires internet, may fail with `network` error behind VPNs/firewalls)
- **Safari (iOS 14.5+/macOS)**: Uses on-device Siri speech recognition (works offline)
- **Firefox**: Not supported (button is hidden)

The button shows a pulsing red indicator while recording. Transcribed text is appended to the textarea in real-time.

**Language selection**: Long-press (500ms) on the microphone button to open a language selector popup. Currently supports English (en-US) and Czech (cs-CZ). The browser's preferred language is shown first if supported. The selected language is persisted to localStorage.

**Auto-stop on send**: Voice recording is automatically stopped when a message is sent (via `stopVoiceRecording()` in `sendMessage()`), preventing transcribed text from being re-added to the cleared input.

## Thinking Indicator

During streaming responses, a thinking indicator shows the model's thinking process and tool usage.

### How it works
1. **Thinking extraction**: The backend extracts thinking content from Gemini's `usage_metadata.thoughts` field in [chat_agent.py](src/agent/chat_agent.py)
2. **Streaming events**: SSE events are sent for thinking (`event: thinking`), tool starts (`event: tool_start`), and tool completions (`event: tool_end`)
3. **Frontend component**: [ThinkingIndicator.ts](web/src/components/ThinkingIndicator.ts) renders the trace with animated indicators
4. **Auto-scroll**: Scrolls to keep thinking visible during streaming (only if user was at bottom when streaming started)
5. **Finalized view**: After streaming ends, collapses into a "Show details" toggle

### Display states
- **Streaming**: Shows full trace with active item at the bottom (for auto-scroll). Active items show animated dots
- **Finalized**: Collapses into toggle button. Clicking expands to show full trace with thinking first, then tools

### Trace ordering
During streaming, thinking stays at the end of the trace (for auto-scroll). Tools are inserted before thinking. When finalized, trace is reordered: thinking first, then tools (logical reading order).

### Markdown support
Thinking text is rendered with markdown formatting for better readability (lists, code blocks, emphasis, etc.).

### Key files
- [chat_agent.py](src/agent/chat_agent.py) - `extract_thinking_and_text()` extracts thinking from Gemini response
- [routes.py](src/api/routes.py) - Streaming generator sends thinking/tool events
- [ThinkingIndicator.ts](web/src/components/ThinkingIndicator.ts) - Component with state management and trace helpers
- [Messages.ts](web/src/components/Messages.ts) - `addStreamingMessage()`, `updateStreamingThinking()`, `updateStreamingToolStart()`, `updateStreamingToolEnd()`
- [thinking.css](web/src/styles/components/thinking.css) - Styles including markdown formatting
- [main.ts](web/src/main.ts) - `handleStreamingResponse()` processes SSE events

### Tool labels
| Tool | Active | Completed |
|------|--------|-----------|
| `web_search` | "Searching the web" | "Searched" |
| `fetch_url` | "Fetching page" | "Fetched" |
| `generate_image` | "Generating image" | "Generated image" |
| `execute_code` | "Running code" | "Ran code" |
| Other | "Running {tool}" | "Used {tool}" |

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
- Shows a confirmation modal before deleting
- Cost data is intentionally preserved after deletion for accurate reporting

**Key files:**
- [Sidebar.ts](web/src/components/Sidebar.ts) - Conversation list rendering, rename/delete handlers
- [main.ts](web/src/main.ts) - `renameConversation()` function
- [Modal.ts](web/src/components/Modal.ts) - `showPrompt()` and `showConfirm()` dialogs

## Touch Gestures

The app uses a reusable swipe gesture system (`createSwipeHandler` in [swipe.ts](web/src/gestures/swipe.ts)):

1. **Conversation swipe actions**: Swipe left on a conversation item to reveal rename and delete buttons, swipe right to close
2. **Sidebar swipe-to-open**: Swipe from left edge (within 50px) to open sidebar, swipe left on main content to close

The swipe handler prevents conflicts by giving priority to more specific gestures (conversation swipes) over global gestures (sidebar edge swipe).

**Important implementation details:**
- All touch handlers include `touchcancel` listeners for iOS Safari, which can cancel touches during system gestures
- The `activeSwipeType` state variable tracks whether a `'conversation'` or `'sidebar'` swipe is in progress to prevent conflicts
- **Critical**: `activeSwipeType` must only be set when actual swiping starts (in `onSwipeMove`), NOT in `shouldStart`. Setting it on touch start causes taps (non-swipes) to block subsequent sidebar swipes since `onComplete`/`onSnapBack` only run when `isSwiping` is true

## iOS Safari Gotchas

When working on mobile/PWA features, beware of these iOS Safari issues:

1. **PWA viewport height** - In a PWA (no address bar), use `position: fixed; inset: 0` on the root container (`#app`) to fill the viewport. The flex children (sidebar and main panel) should use `align-self: stretch` (default) to fill the container height. Avoid explicit `height: 100vh` or `height: 100%` on flex children - let flexbox handle it naturally. See [layout.css](web/src/styles/layout.css) for the working implementation.

2. **Inline `onclick` handlers don't work reliably** - Use event delegation instead of inline `onclick` on dynamically created elements. Attach listeners to parent containers.

3. **PWA caching is aggressive** - Users may need to remove and re-add the app to home screen to see changes. Vite handles cache busting via hashed filenames.

4. **Touch events can be cancelled** - iOS Safari may cancel touch sequences during system gestures (e.g., Control Center swipe, incoming calls). Always handle `touchcancel` events to reset gesture state.

5. **PWA keyboard scroll miscalculation** - iOS Safari in PWA mode miscalculates the scroll position when the keyboard opens, causing the cursor to appear below the input initially. The fix uses the `visualViewport` API to detect when the keyboard opens (viewport height shrinks) and scrolls the input area into view. See `isIOSPWA()` in [MessageInput.ts](web/src/components/MessageInput.ts).

## Performance Optimizations

### Conversation Loading
- **Optimized payload**: `/api/conversations/<conv_id>` only sends file metadata (name, type, messageId, fileIndex), not thumbnails or full file data
- **Thumbnails on demand**: Thumbnails are fetched via `/api/messages/<message_id>/files/<file_index>/thumbnail` when images come into view
- **Full files on demand**: Full files are fetched via `/api/messages/<message_id>/files/<file_index>` when needed (lightbox, downloads)
- **Lazy loading**: Frontend uses Intersection Observer to load thumbnails in parallel as user scrolls
- **Parallel fetching**: Up to 6 thumbnails fetch concurrently when images come into viewport
- **Loading indicators**: Visual feedback during conversation switching and thumbnail loading

### File Handling
- Thumbnails are generated server-side using Pillow (400x400px max) and stored in the database with messages
- Frontend prefers thumbnails over full images for display
- If a thumbnail is missing (e.g., old messages), the full image is fetched from API on-demand when visible
- Native browser lazy loading (`loading="lazy"`) is used for all images
- Parallel fetching: Up to 6 missing images fetch concurrently when they come into viewport

### Token Usage Optimization

The app implements several optimizations to minimize token costs:

1. **History files excluded**: When building conversation history for the LLM, files (images, PDFs) from previous messages are NOT re-sent. Only the current message's files are included. This prevents large base64 data from being sent repeatedly with every request.

2. **Generated images not sent back to LLM**: When the `generate_image` tool runs, the full image data (~500KB base64) is stored in a `_full_result` field that gets stripped before the tool result goes back to the LLM. The LLM only sees a success confirmation message. This prevents ~650K tokens of base64 from being charged on every image generation.

**How the `_full_result` stripping works:**
1. `generate_image` tool returns JSON with `_full_result.image` containing the base64 image data
2. A custom tool node wrapper (`create_tool_node()`) intercepts tool results before they go to the LLM
3. The wrapper captures the FULL tool results (with `_full_result`) in a global dict keyed by request ID
4. It then strips `_full_result` from the tool message content before the LLM sees it
5. After the LLM finishes, the routes layer retrieves the full results using `get_full_tool_results(request_id)`
6. Images and costs are extracted from the full results for storage and display

**Threading considerations for streaming:**
- The streaming endpoint uses a background thread for LLM streaming
- Context variables (used to track request ID) don't automatically inherit to new threads in Python
- The background thread explicitly calls `set_current_request_id()` to set up its own context

**IMPORTANT - `get_full_tool_results()` pops results:**
- `get_full_tool_results(request_id)` **removes** results from the dict when called (it's a `.pop()`)
- You can only call it ONCE per request - subsequent calls return empty list
- In streaming, `save_message_to_db()` returns a `SaveResult` object with extracted data
- The done event builder reuses data from `SaveResult` instead of calling `get_full_tool_results()` again
- If you need the results in multiple places, store them in a variable after the first call

**Implementation details:**
- [tools.py](src/agent/tools.py) - `generate_image` returns image in `_full_result` field
- [chat_agent.py](src/agent/chat_agent.py) - `create_tool_node()` wraps ToolNode to strip `_full_result`, `set_current_request_id()` and `get_full_tool_results()` for per-request capture
- [images.py](src/utils/images.py) - `extract_generated_images_from_tool_results()` extracts images from `_full_result`
- [routes.py](src/api/routes.py) - Sets request ID before agent call, retrieves full results after, passes to image extraction and cost calculation

### Scroll-to-Bottom Behavior

The app automatically scrolls to the bottom when loading conversations and when new messages are added, but handles lazy-loaded images specially to avoid scrolling before images have loaded and affected the layout.

**How it works:**
1. **Initial conversation load**: When `renderMessages()` is called, it always scrolls to bottom immediately to ensure latest messages are visible and images at the bottom become visible (triggering IntersectionObserver)
2. **Track image loads**: Each image that starts loading increments a `pendingImageLoads` counter
3. **Wait for completion**: The code waits for each image's `load` event (not just the fetch) to ensure it has fully rendered
4. **Debounced smooth scroll**: When all images finish loading (`pendingImageLoads === 0`), a smooth scroll animation is triggered after layout has settled
5. **Smooth animation**: Uses custom ease-out-cubic easing with duration based on scroll distance (300-600ms)

**New message additions (batch and streaming):**
When a new message with images is added (via `sendBatchMessage()` or `finalizeStreamingMessage()`):
- Checks if the message has images that need loading (images without `previewUrl`)
- Checks if user was already at the bottom (`isScrolledToBottom()`)
- If both conditions are true: enables `scrollOnImageLoad()` so images are tracked when observed
- **Batch mode**: Message is added via `addMessageToUI()` (images are created and observed synchronously)
- **Streaming mode**: Images are added via `renderMessageFiles()` in `finalizeStreamingMessage()` (images are created and observed synchronously)
- Scrolls to bottom immediately (non-smooth) to ensure images are visible
- Uses double `requestAnimationFrame` to ensure scroll completed and layout settled
- Fallback: Checks if images are visible but haven't started loading, and re-observes them to trigger intersection check
- IntersectionObserver fires for visible images (either immediately or after re-observation)
- Scroll happens automatically after all images finish loading
- If no images or user wasn't at bottom: scrolls immediately (if at bottom)

**Smooth scroll implementation:**
- Custom animation in `scrollToBottom()` with ease-out-cubic easing
- Used both for button clicks and automatic scrolls after image loading
- Prevents abrupt flashing when images load and push content down

**User scroll detection:**
The app tracks user scrolls to disable auto-scroll when the user is browsing history:
- A scroll listener is set up when `enableScrollOnImageLoad()` is called
- If the user scrolls more than 200px from the bottom, auto-scroll is disabled
- This prevents hijacking the scroll position when the user is viewing older messages
- **Critical**: The scroll listener distinguishes between user scrolls and programmatic scrolls (see Programmatic Scroll Wrapper below)

**Scroll hijacking prevention:**
When images load while the user is scrolled up, the system checks scroll position at multiple points to prevent race conditions:
- **Image load completion**: When an image finishes loading, the handler immediately checks scroll position using `isScrolledToBottom()` BEFORE decrementing `pendingImageLoads`. This prevents a race condition where layout changes from image loading could make the scroll position appear >200px from bottom, causing incorrect disabling. By checking BEFORE, we capture the state before layout changes affect the check.
- **Scheduled scroll protection**: The `isSchedulingScroll` flag prevents the user scroll listener from disabling scroll mode while a scroll is actively being scheduled. This prevents false positives from layout shifts during image loading.
- **Safe disable function**: `safelyDisableScrollOnImageLoad()` checks `isSchedulingScroll` before actually disabling scroll mode. This centralizes the logic and prevents race conditions.
- **Scheduled scroll**: `scheduleScrollAfterImageLoad()` re-checks `shouldScrollOnImageLoad` inside nested RAFs and ignores scroll-away checks when `isSchedulingScroll` is true (layout changes can cause false positives).
- **Final verification**: Verifies the user is still at/near the bottom using `isScrolledToBottom()` before actually scrolling
- If the user has scrolled up at any point, disables scroll mode immediately and returns early (prevents hijacking)

**Race condition fixes:**
1. **Image load timing**: The scroll listener has a 100ms debounce, but images can load faster than that. Without the immediate scroll position check in the image load handler, an image could finish loading while `shouldScrollOnImageLoad` is still `true` (because the debounced handler hasn't run yet), causing an unwanted scroll. The fix checks scroll position synchronously when the image finishes loading, ensuring we never scroll when the user has scrolled up, regardless of timing.

2. **Layout shift false positives**: When images load, they cause layout shifts that can temporarily make it appear the user has scrolled away from the bottom (scrollHeight increases, making distanceFromBottom > 200px). The `isSchedulingScroll` flag prevents the user scroll listener from disabling scroll mode during these layout shifts, and `scheduleScrollAfterImageLoad()` ignores scroll-away checks when `isSchedulingScroll` is true.

3. **Cached images on initial load**: On initial load, images may load instantly from cache before IntersectionObserver fires or before we can count them. The system checks ALL images (not just tracked ones) when `pendingImageLoads` is 0, and verifies all tracked images are actually loaded before scheduling scroll. This handles race conditions where multiple images load instantly (most commonly observed with 2 images, but applies to any number).

**Key files:**
- [thumbnails.ts](web/src/utils/thumbnails.ts) - Image load tracking, `enableScrollOnImageLoad()`, `scheduleScrollAfterImageLoad()`, `programmaticScrollToBottom()`, user scroll detection
- [dom.ts](web/src/utils/dom.ts) - `scrollToBottom()` with smooth animation, `isScrolledToBottom()`
- [Messages.ts](web/src/components/Messages.ts) - `renderMessages()` always scrolls to bottom first
- [main.ts](web/src/main.ts) - `sendBatchMessage()` handles scroll logic for new messages with images
- [ScrollToBottom.ts](web/src/components/ScrollToBottom.ts) - Button component that triggers smooth scroll

### Programmatic Scroll Wrapper

The app uses a programmatic scroll wrapper to distinguish between user-initiated scrolls and app-initiated scrolls, preventing the user scroll listener from incorrectly disabling auto-scroll.

**Why it exists:**
- The user scroll listener disables auto-scroll when the user scrolls up (browsing history)
- Without the wrapper, programmatic scrolls (from `scrollToBottom()`, `renderMessages()`, etc.) would be detected as user scrolls
- This would cause auto-scroll to be disabled immediately after the app scrolls, breaking the scroll-on-image-load behavior

**How it works:**
- `programmaticScrollToBottom()` automatically sets programmatic scroll markers before and after scrolling
- The scroll listener checks `isProgrammaticScroll` flag and ignores programmatic scrolls
- Markers are cleared after a short delay (150ms) to ensure scroll events have fired

**When to use:**
- **Always use `programmaticScrollToBottom()`** instead of raw `scrollToBottom()` for any programmatic scroll operations
- This includes:
  - Scrolling after rendering messages
  - Scrolling after adding new messages
  - Scrolling after images load
  - Any other app-initiated scroll operations

**How to use:**
```typescript
import { programmaticScrollToBottom } from './utils/thumbnails';

// Instead of:
scrollToBottom(container, false);

// Use:
programmaticScrollToBottom(container, false);

// For smooth scrolling:
programmaticScrollToBottom(container, true);
```

**Implementation details:**
- `markProgrammaticScrollStart()` - Sets flag before scroll
- `markProgrammaticScrollEnd()` - Clears flag after scroll (with 150ms delay for scroll events)
- `programmaticScrollToBottom()` - Convenience wrapper that handles markers automatically
- For smooth scrolls, waits 700ms before clearing the flag (smooth scroll takes 300-600ms)

**Key files:**
- [thumbnails.ts](web/src/utils/thumbnails.ts) - `programmaticScrollToBottom()`, `markProgrammaticScrollStart()`, `markProgrammaticScrollEnd()`, user scroll listener

### Streaming Auto-Scroll

During streaming responses, a separate scroll system manages auto-scrolling to keep the latest content visible while allowing user interruption.

**How it works:**
1. **Initial state**: When `addStreamingMessage()` is called, it checks if user is at bottom
2. **Scroll listener**: A streaming-specific scroll listener is set up to detect user scroll
3. **Auto-scroll during streaming**: `autoScrollForStreaming()` scrolls to bottom after each content update (thinking, tool, token)
4. **User interruption**: If user scrolls up (away from bottom), auto-scroll is paused
5. **Auto-scroll resume**: If user scrolls back to bottom, auto-scroll resumes automatically
6. **Cleanup**: When streaming ends (success or error), the scroll listener is cleaned up

**Key behaviors:**
- **Interruptible**: User can scroll up during streaming to read history - auto-scroll pauses
- **Resumable**: User can scroll back to bottom to resume auto-scroll
- **Threshold-based**: Uses 100px threshold to determine "at bottom" state (more lenient than 200px used for image loading)
- **Debounced**: 50ms debounce on scroll detection to avoid excessive processing

**User message scroll:**
When user sends a message, the app scrolls to bottom immediately after adding the user message to the UI. This ensures the user's message is visible before the assistant's response starts streaming.

**Key files:**
- [Messages.ts](web/src/components/Messages.ts) - `addStreamingMessage()`, `setupStreamingScrollListener()`, `autoScrollForStreaming()`, `cleanupStreamingContext()`
- [main.ts](web/src/main.ts) - `sendMessage()` scrolls after adding user message, `sendStreamingMessage()` cleans up context in finally block

**Testing:**
E2E tests for streaming auto-scroll are in [chat.spec.ts](web/tests/e2e/chat.spec.ts) under "Chat - Streaming Auto-Scroll" describe block:
- `scrolls to bottom when sending a new message`
- `auto-scroll can be interrupted by scrolling up during streaming`
- `auto-scroll resumes when scrolling back to bottom during streaming`

## Real-time Synchronization

The app syncs conversation state across multiple devices/tabs using timestamp-based polling.

### Architecture

Chosen **polling over SSE/WebSockets** because:
- Simple - no persistent connections or reconnection logic
- Already indexed - uses existing `idx_conversations_user_id_updated_at` index
- No write overhead - `updated_at` already updates on changes
- Appropriate scale - single-user/small-user app
- Robust - each poll is independent

### How it works

1. **Full sync**: On initial load or after >5 minutes hidden, fetches all conversations with message counts
2. **Incremental sync**: Every 60 seconds, fetches only conversations updated since last sync
3. **Unread count**: `unreadCount = server_message_count - local_message_count`
4. **Delete detection**: Full sync compares local IDs with server response; missing = deleted
5. **Visibility-aware**: Polling pauses when tab is hidden, syncs immediately on refocus

### UI indicators

- **Unread badge**: Shows count on conversations with new messages (sidebar)
- **New messages banner**: Appears when current conversation has external updates
- Badge shows "99+" for counts over 99
- **Badge clearing**: When user clicks a conversation, `switchToConversation()` calls both `markConversationRead()` AND `renderConversationsList()` to update the store and re-render the sidebar

### Race condition handling

The SyncManager handles several race conditions:

1. **Concurrent sync prevention**: `isSyncing` lock prevents multiple syncs from running simultaneously
2. **Streaming protection**: Conversations being actively streamed are skipped during sync to prevent false unread counts
3. **Clock skew**: Always uses `server_time` from response, never client time
4. **Message boundary**: Server returns `server_time` that becomes next sync's `since` param

### Configuration

```typescript
// web/src/config.ts
SYNC_POLL_INTERVAL_MS = 60 * 1000;      // 1 minute
SYNC_FULL_SYNC_THRESHOLD_MS = 5 * 60 * 1000;  // 5 minutes
```

### Key files

- [SyncManager.ts](web/src/sync/SyncManager.ts) - Polling, state sync, race condition handling
- [models.py](src/db/models.py) - `list_conversations_with_message_count()`, `get_conversations_updated_since()`
- [routes.py](src/api/routes.py) - `GET /api/conversations/sync` endpoint
- [Sidebar.ts](web/src/components/Sidebar.ts) - Unread badge rendering
- [main.ts](web/src/main.ts) - New messages banner, streaming integration

### Testing

- Backend: [test_routes_sync.py](tests/integration/test_routes_sync.py) - Integration tests for sync endpoint
- Frontend: [sync-manager.test.ts](web/tests/unit/sync-manager.test.ts) - SyncManager unit tests
- E2E: [sync.spec.ts](web/tests/e2e/sync.spec.ts) - Multi-tab and visibility scenarios
- Visual: [chat.visual.ts](web/tests/visual/chat.visual.ts) - Sync UI visual tests (unread badge, banner)

## Version Update Banner

The app detects when a new version is deployed and shows a banner prompting users to reload.

### How it works
1. **Version source**: The Vite JS bundle hash (e.g., `main-y-VVsbiY.js` → `y-VVsbiY`) serves as the version identifier
2. **Initial load**: Flask extracts the version from the Vite manifest and injects it into the HTML via `data-version` attribute on `#app`
3. **Periodic polling**: Frontend polls `GET /api/version` every 5 minutes (no auth required)
4. **PWA awareness**: Polling pauses when tab is hidden (`document.visibilitychange`), checks immediately on refocus if >5 min since last check
5. **Dismiss persistence**: Dismissed versions are stored in localStorage to avoid re-showing the same banner

### Key files
- [app.py](src/app.py) - Extracts version hash from manifest, stores in `app.config["APP_VERSION"]`
- [routes.py](src/api/routes.py) - `GET /api/version` endpoint
- [VersionBanner.ts](web/src/components/VersionBanner.ts) - Banner component and polling logic
- [store.ts](web/src/state/store.ts) - `appVersion`, `newVersionAvailable`, `versionBannerDismissed` state

### Testing locally
In development mode, the version will be `null` (no manifest). Use the test helper in browser console:
```javascript
window.__testVersionBanner()
```

## Cost Tracking

The app tracks API costs per conversation and per user per calendar month, accounting for token usage and image generation.

### How it works
1. **Token usage tracking**: Token counts are extracted from `usage_metadata` in LangChain's `AIMessage` and `AIMessageChunk` objects (both batch and streaming modes)
2. **Image generation costs**: Image generation costs are calculated from `usage_metadata` returned by the Gemini image generation API
3. **Cost calculation**: Costs are calculated using model pricing from [config.py](src/config.py) and converted to the configured currency (default: CZK)
4. **Database storage**: Costs are stored in the `message_costs` table with token counts and total cost in USD
5. **UI display**:
   - Conversation cost is shown under the input box (updates after each message)
   - Monthly cost is shown in the sidebar footer (clickable to view history)
   - Cost history popup shows monthly breakdown with total
   - Message cost button (dollar icon) appears on assistant messages, opening a popup with detailed cost breakdown
   - Image generation popup shows the cost of image generation only (excluding prompt tokens)

### Key files
- [costs.py](src/utils/costs.py) - Cost calculation and currency conversion utilities
- [config.py](src/config.py) - Model pricing (`MODEL_PRICING`) and currency rates (`CURRENCY_RATES`)
- [models.py](src/db/models.py) - `save_message_cost()`, `get_message_cost()`, `get_conversation_cost()`, `get_user_monthly_cost()`, `get_user_cost_history()` (note: `delete_conversation()` intentionally preserves cost data for accurate reporting)
- [chat_agent.py](src/agent/chat_agent.py) - Token usage extraction from `usage_metadata` (memory efficient - only tracks numbers, not message objects)
- [tools.py](src/agent/tools.py) - Image generation tool includes `usage_metadata` in response
- [api/utils.py](src/api/utils.py) - `calculate_and_save_message_cost()` centralizes cost calculation and saving for both batch and streaming, `calculate_image_generation_cost_from_tool_results()` extracts image costs from tool results
- [routes.py](src/api/routes.py) - Calls `calculate_and_save_message_cost()` in batch/stream endpoints, cost API endpoints (`/api/messages/<message_id>/cost`, `/api/conversations/<conv_id>/cost`, `/api/users/me/costs/*`)
- [main.ts](web/src/main.ts) - `updateConversationCost()` updates cost display after messages
- [CostHistoryPopup.ts](web/src/components/CostHistoryPopup.ts) - Cost history popup component
- [MessageCostPopup.ts](web/src/components/MessageCostPopup.ts) - Message cost popup component
- [ImageGenPopup.ts](web/src/components/ImageGenPopup.ts) - Image generation popup (shows image generation cost)
- [Sidebar.ts](web/src/components/Sidebar.ts) - Monthly cost display in footer
- [Messages.ts](web/src/components/Messages.ts) - Cost button rendering in message actions

### Cost calculation details
- **Token costs**: Calculated from `input_tokens` and `output_tokens` using per-million-token pricing
- **Image generation costs**: Calculated from `usage_metadata` with separate pricing for prompt tokens (input) and candidate/thought tokens (output). Stored separately in `image_generation_cost_usd` column for display in image generation popup
- **Other tools**: Web search and URL fetching are free (no cost tracking)
- **Currency conversion**: Costs are stored in USD, converted to display currency (configurable via `COST_CURRENCY` env var)

### Database schema
The `message_costs` table stores:
- `cost_usd`: Total cost (tokens + image generation)
- `image_generation_cost_usd`: Cost of image generation only (separate from token costs)
- Token counts and model information for detailed breakdown

### Memory efficiency
Token usage is tracked efficiently during streaming by extracting and accumulating counts immediately from each chunk, rather than storing entire message objects. Only the final token counts are kept in memory.

### Configuration
- `COST_CURRENCY`: Display currency (default: `CZK`)
- `MODEL_PRICING`: Model pricing per million tokens (in [config.py](src/config.py))
- `CURRENCY_RATES`: Exchange rates for currency conversion (in [config.py](src/config.py))
- `COST_HISTORY_MAX_MONTHS`: Maximum number of months for cost history queries (default: `120`)
- `COST_HISTORY_DEFAULT_LIMIT`: Default number of months for cost history queries (default: `12`)
- `STREAM_CLEANUP_THREAD_TIMEOUT`: Timeout for cleanup thread waiting for stream thread (default: `600` seconds)
- `STREAM_CLEANUP_WAIT_DELAY`: Delay before checking if message was saved (default: `1.0` seconds)
- `GOOGLE_AUTH_TIMEOUT`: Timeout for Google token verification (default: `10` seconds)
- `THUMBNAIL_MAX_SIZE`: Maximum thumbnail dimensions (default: `(400, 400)`)
- `THUMBNAIL_QUALITY`: JPEG quality for thumbnails (default: `85`)

**Note**: Currency rates and model pricing are currently hardcoded in `config.py`. See [TODO.md](TODO.md) for planned automated updates. All configuration values can be overridden via environment variables (see `.env.example`).

## User Context

The LLM system prompt can include user context to provide more personalized and contextually appropriate responses.

### Configuration
- `USER_LOCATION`: User's location for contextual responses (e.g., "Prague, Czech Republic" or "New York, USA")
  - When set, the LLM is instructed to:
    - Use appropriate measurement units (metric vs imperial) based on local conventions
    - Prefer local currency when discussing prices
    - Recommend locally available retailers/services when relevant
    - Consider local regulations, holidays, and cultural context
    - Use appropriate date/time formats for the locale

### How it works
1. **Location from config**: `USER_LOCATION` is read from environment/config (shared across all users of this deployment)
2. **User name from JWT**: The authenticated user's name is passed from the JWT token
3. **System prompt injection**: `get_user_context()` in [chat_agent.py](src/agent/chat_agent.py) builds the context section
4. **Prompt integration**: `get_system_prompt()` includes the user context when building the system prompt

### Key files
- [config.py](src/config.py) - `USER_LOCATION` configuration
- [chat_agent.py](src/agent/chat_agent.py) - `get_user_context()`, `get_system_prompt()` with `user_name` parameter
- [routes.py](src/api/routes.py) - Passes `user_name` from authenticated user to chat methods

## User Memory

The LLM can learn and remember interesting facts about the user across conversations for personalization.

### Design decisions
- **Delete only**: Users can view and delete memories, but not edit them (prevents fake memories)
- **100 memory limit**: With LLM-managed rotation when near limit
- **LLM deduplication**: LLM sees existing memories and decides to update/consolidate/remove
- **Categories**: `preference`, `fact`, `context`, `goal`

### How it works

1. **Injection**: Current memories are injected into the system prompt with timestamps and IDs
2. **Extraction**: LLM includes memory operations in a metadata block at the end of responses
3. **Processing**: Backend processes operations (add/update/delete) after response completion
4. **Management**: Users can view/delete memories via brain icon button in sidebar

### Memory operations format

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

### Key files

**Backend:**
- [migrations/0009_add_user_memories.py](migrations/0009_add_user_memories.py) - Database migration
- [models.py](src/db/models.py) - `Memory` dataclass, CRUD methods (`add_memory`, `update_memory`, `delete_memory`, `list_memories`)
- [chat_agent.py](src/agent/chat_agent.py) - `MEMORY_SYSTEM_PROMPT`, `get_user_memories_prompt()`
- [utils.py](src/api/utils.py) - `extract_memory_operations()` for parsing metadata
- [routes.py](src/api/routes.py) - Memory processing in chat endpoints, `GET /api/memories`, `DELETE /api/memories/<id>`
- [config.py](src/config.py) - `USER_MEMORY_LIMIT` constant (default: 100)

**Frontend:**
- [MemoriesPopup.ts](web/src/components/MemoriesPopup.ts) - Popup component with category badges, delete confirmation
- [Sidebar.ts](web/src/components/Sidebar.ts) - Brain icon button trigger
- [client.ts](web/src/api/client.ts) - `memories.list()`, `memories.delete()` API methods
- [api.ts](web/src/types/api.ts) - `Memory`, `MemoriesResponse` types
- [icons.ts](web/src/utils/icons.ts) - `BRAIN_ICON`
- [popups.css](web/src/styles/components/popups.css) - `.memory-item`, `.memory-category` styles

### Testing
- Backend integration tests: [test_routes_memories.py](tests/integration/test_routes_memories.py)
- Visual tests: `popup-memories.png`, `popup-memories-empty.png`, `mobile-popup-memories.png` in [popups.visual.ts](web/tests/visual/popups.visual.ts)

## Custom Instructions

Users can customize LLM behavior via a free-text custom instructions field in the settings popup.

### How it works

1. **Storage**: Custom instructions are stored in the `users.custom_instructions` column (up to 2000 characters)
2. **UI**: Settings popup accessible via gear icon button in sidebar (next to memories and logout)
3. **Injection**: Instructions are appended to the system prompt via `CUSTOM_INSTRUCTIONS_PROMPT` constant
4. **Immediate effect**: Changes apply to new messages immediately (no restart needed)

### Example use cases
- "Respond in Czech"
- "Be concise, use bullet points"
- "Explain things like I'm a beginner"
- "Always provide code examples in Python"

### API endpoints
- `GET /api/users/me/settings` - Returns `{ custom_instructions: string }`
- `PATCH /api/users/me/settings` - Updates settings, body: `{ custom_instructions: string | null }`

### Key files

**Backend:**
- [migrations/0010_add_custom_instructions.py](migrations/0010_add_custom_instructions.py) - Database migration
- [models.py](src/db/models.py) - `User.custom_instructions` field, `update_user_custom_instructions()` method
- [chat_agent.py](src/agent/chat_agent.py) - `CUSTOM_INSTRUCTIONS_PROMPT` constant, `get_system_prompt()` with `custom_instructions` parameter
- [schemas.py](src/api/schemas.py) - `UpdateSettingsRequest` schema with 2000 char limit
- [routes.py](src/api/routes.py) - Settings endpoints, passes `custom_instructions` to agent

**Frontend:**
- [SettingsPopup.ts](web/src/components/SettingsPopup.ts) - Settings popup with textarea, character count, save button
- [Sidebar.ts](web/src/components/Sidebar.ts) - Gear icon button in user actions
- [client.ts](web/src/api/client.ts) - `settings.get()`, `settings.update()` API methods
- [api.ts](web/src/types/api.ts) - `UserSettings` type
- [icons.ts](web/src/utils/icons.ts) - `SETTINGS_ICON`
- [popups.css](web/src/styles/components/popups.css) - `.settings-*` styles

### Testing
- Backend integration tests: [test_routes_settings.py](tests/integration/test_routes_settings.py)
- E2E tests: [settings.spec.ts](web/tests/e2e/settings.spec.ts)
- Visual tests: `popup-settings.png`, `popup-settings-empty.png`, `popup-settings-warning.png` in [popups.visual.ts](web/tests/visual/popups.visual.ts)

## Real-time Data Synchronization

The app supports synchronization of conversation state across multiple devices/tabs using timestamp-based polling.

### Design Decision: Polling over SSE/WebSockets

The app uses timestamp-based polling with `updated_at` instead of SSE or WebSockets because:
1. **Simplicity**: No new infrastructure or persistent connections to manage
2. **Already indexed**: The `idx_conversations_user_id_updated_at` composite index exists
3. **No write overhead**: `updated_at` is already updated on message addition
4. **Appropriate scale**: Single-user/small-user app (email whitelist)
5. **Robust**: Each poll is independent, no reconnection logic needed

### How it works

1. **Sync endpoint**: `GET /api/conversations/sync` returns conversations with message counts
   - Query params: `since` (ISO timestamp), `full` (boolean for delete detection)
   - Returns: `conversations`, `server_time`, `is_full_sync`

2. **SyncManager**: Frontend component that manages polling and state updates
   - Performs initial full sync on login
   - Polls every 1 minute (configurable via `SYNC_POLL_INTERVAL_MS`)
   - Performs full sync after 5 minutes of tab inactivity (for delete detection)
   - Pauses polling when tab is hidden, resumes on visibility

3. **Unread count calculation**: `unreadCount = server_message_count - local_message_count`
   - Shown as badge on sidebar conversation items
   - Cleared when user views the conversation

4. **Delete detection**: Full sync compares local conversation IDs with server response
   - Conversations missing from server are removed from local state
   - Shows toast if user was viewing a deleted conversation

5. **External update notification**: When current conversation has new messages from another device
   - Shows "New messages available" banner at top of messages
   - User clicks to reload and see new messages

### Configuration

```python
# src/config.py
SYNC_POLL_INTERVAL_SECONDS = 60  # Not currently used by backend (frontend-only polling)
```

```typescript
// web/src/config.ts
export const SYNC_POLL_INTERVAL_MS = 1 * MS_PER_MINUTE;  // 1 minute
export const SYNC_FULL_SYNC_THRESHOLD_MS = 5 * MS_PER_MINUTE;  // 5 minutes
```

### Key files

**Backend:**
- [routes.py](src/api/routes.py) - `GET /api/conversations/sync` endpoint
- [models.py](src/db/models.py) - `list_conversations_with_message_count()`, `get_conversations_updated_since()`

**Frontend:**
- [SyncManager.ts](web/src/sync/SyncManager.ts) - Polling and state sync logic
- [api/client.ts](web/src/api/client.ts) - `conversations.sync()` method
- [main.ts](web/src/main.ts) - SyncManager initialization and callbacks
- [Sidebar.ts](web/src/components/Sidebar.ts) - Unread count badge rendering
- [config.ts](web/src/config.ts) - `SYNC_POLL_INTERVAL_MS`, `SYNC_FULL_SYNC_THRESHOLD_MS`

**Styles:**
- [sidebar.css](web/src/styles/components/sidebar.css) - `.unread-badge` styles
- [messages.css](web/src/styles/components/messages.css) - `.new-messages-banner` styles

**Types:**
- [api.ts](web/src/types/api.ts) - `ConversationSummary`, `SyncResponse` types, sync fields on `Conversation`

**Tests:**
- [test_routes_sync.py](tests/integration/test_routes_sync.py) - Integration tests for sync endpoint
- [test_db_models.py](tests/integration/test_db_models.py) - Unit tests for sync database methods
- [sync-manager.test.ts](web/tests/unit/sync-manager.test.ts) - Unit tests for SyncManager

### Edge cases handled

1. **Clock skew**: Always uses `server_time` from response, not client time
2. **Race on send**: User sends message, poll happens before save - not a problem (optimistic UI)
3. **Viewing updated conversation**: Shows "New messages" banner, doesn't auto-inject
4. **Offline → Online**: On visibility change, syncs immediately
5. **Deleted while viewing**: Shows toast and clears current conversation
6. **Temp conversations**: Not synced (start with `temp-` prefix, not yet persisted)

### Future optimizations (TODO)

- Consider soft delete (`deleted_at` column) for more efficient delete detection
- BroadcastChannel for multi-tab coordination if needed

## Common Tasks

### Add a new API endpoint
Edit [routes.py](src/api/routes.py), add route to `api` blueprint.

### Add a new tool to the agent
Edit [tools.py](src/agent/tools.py), add function with `@tool` decorator and add to `TOOLS` list.

### Change available models
Edit [config.py](src/config.py) `MODELS` dict.

### Add a new UI component
1. Create TypeScript file in `web/src/components/`
2. Export init function and render functions
3. Import and wire in `main.ts`

### Add new icons
Add SVG constants to [icons.ts](web/src/utils/icons.ts) and import where needed.

## CSS Architecture

The frontend uses a modular CSS architecture with design tokens for consistency.

### File Structure

```
web/src/styles/
├── main.css           # Entry point (imports all modules)
├── variables.css      # Design system tokens
├── base.css           # Reset, typography, utilities
├── layout.css         # App shell structure
└── components/
    ├── buttons.css    # All button variants
    ├── messages.css   # Message display, avatars, content
    ├── sidebar.css    # Conversation list, swipe actions
    ├── input.css      # Input toolbar, model selector, file preview
    └── popups.css     # Modals, toasts, lightbox, info popups
```

### Design System Variables

All design tokens are defined in [variables.css](web/src/styles/variables.css):

**Colors:**
- Neutral scale: `--color-neutral-950` (darkest) to `--color-neutral-100` (lightest)
- Brand colors: `--color-brand-400` to `--color-brand-950` (indigo/purple)
- Semantic: `--color-success-*`, `--color-error-*`, `--color-warning-*`
- Aliases: `--bg-primary`, `--text-primary`, `--accent`, `--border` (for easier use)

**Spacing:**
- Scale: `--space-1` (4px) to `--space-12` (48px)

**Typography:**
- Sizes: `--font-size-xs` to `--font-size-4xl`
- Family: `--font-family` (system), `--font-family-mono`

**Other tokens:**
- Border radius: `--radius-xs` to `--radius-full`
- Shadows: `--shadow-sm`, `--shadow-md`, `--shadow-lg`
- Transitions: `--transition-fast`, `--transition-normal`, `--transition-slow`
- Z-index: `--z-dropdown`, `--z-modal`, `--z-toast`, etc.

### Adding New Styles

1. **New component**: Create file in `components/`, import in `main.css`
2. **New color**: Add to palette in `variables.css`, create semantic alias if needed
3. **Reusable pattern**: Add to appropriate component file or create new one

### Key Files

- [variables.css](web/src/styles/variables.css) - Design tokens
- [layout.css](web/src/styles/layout.css) - App shell, responsive breakpoints
- [components/buttons.css](web/src/styles/components/buttons.css) - Button variants
- [components/popups.css](web/src/styles/components/popups.css) - Modals, toasts, overlays

## Testing

The project has comprehensive test suites for both backend and frontend.

### Backend Test Structure

```
tests/
├── conftest.py                    # Shared fixtures (database, app, auth, mocks)
├── fixtures/
│   └── images.py                  # Test image generators
├── mocks/
│   └── gemini.py                  # Mock LLM response builders
├── unit/                          # Unit tests (isolated function testing)
│   ├── test_costs.py              # Cost calculations
│   ├── test_jwt_auth.py           # JWT token handling
│   ├── test_google_auth.py        # Google token verification
│   ├── test_chat_agent_helpers.py # Agent helper functions
│   ├── test_images.py             # Image processing
│   └── test_tools.py              # Agent tools (mocked externals)
├── integration/                   # Integration tests (multi-component)
│   ├── test_db_models.py          # Database CRUD operations
│   ├── test_routes_auth.py        # Auth endpoints
│   ├── test_routes_conversations.py  # Conversation CRUD
│   ├── test_routes_chat.py        # Chat endpoints
│   └── test_routes_costs.py       # Cost tracking endpoints
└── e2e-server.py                  # Mock Flask server for E2E tests (with SSE streaming)
```

### Frontend Test Structure

```
web/tests/
├── global-setup.ts                # Playwright test setup (DB reset before each test)
├── unit/                          # Vitest unit tests
│   ├── setup.ts                   # Test setup (jsdom config)
│   ├── api-client.test.ts         # API client utilities (retry, timeout, errors)
│   ├── dom.test.ts                # DOM utilities (escapeHtml, scrollToBottom)
│   ├── store.test.ts              # Zustand store
│   ├── toast.test.ts              # Toast notification component
│   └── modal.test.ts              # Modal dialog component
├── component/                     # Component tests with jsdom
│   └── Sidebar.test.ts            # Sidebar interactions
├── e2e/                           # Playwright E2E tests (2 browsers)
│   ├── auth.spec.ts               # Authentication flow
│   ├── chat.spec.ts               # Chat functionality (batch + streaming)
│   ├── conversation.spec.ts       # Conversation CRUD
│   └── mobile.spec.ts             # Mobile viewport tests
└── visual/                        # Visual regression tests
    ├── chat.visual.ts             # Chat interface screenshots
    ├── mobile.visual.ts           # Mobile layout screenshots
    ├── error-ui.visual.ts         # Error UI (toast, modal, version banner)
    └── popups.visual.ts           # Popups (sources, cost, image gen, lightbox)
```

### Key Testing Patterns

**Backend:**
- **Isolated SQLite per test**: Each test gets its own database file for complete isolation
- **Mocked external services**: Gemini LLM, Google Auth, DuckDuckGo, httpx are all mocked
- **Shared fixtures**: Use `test_user`, `test_conversation`, `auth_headers` from conftest.py
- **Flask test client**: Use the `client` fixture for HTTP testing

**Frontend:**
- **Vitest for unit/component tests**: Fast, TypeScript-native, uses jsdom for DOM simulation
- **Playwright for E2E tests**: Real browser testing (chromium, webkit), mock server
- **E2E test isolation**: Each test resets database via `/test/reset` endpoint
- **Mock LLM server**: `tests/e2e-server.py` runs Flask with mocked Gemini responses
- **E2E auth bypass**: Tests set `E2E_TESTING=true` to skip auth (separate from unit test mode)

### Running Tests

```bash
# Backend tests
make test              # Run all backend tests
make test-unit         # Run unit tests only
make test-integration  # Run integration tests only
make test-cov          # Run with coverage report

# Frontend tests (from project root)
make test-fe           # Run unit + component + E2E tests (functional tests)
make test-fe-unit      # Run Vitest unit tests
make test-fe-component # Run component tests
make test-fe-e2e       # Run Playwright E2E tests
make test-fe-visual    # Run visual regression tests - see below
make test-fe-watch     # Run Vitest in watch mode

# All tests
make test-all          # Run backend + frontend (excl. visual)
```

**Note on Visual Tests**: Visual tests are intentionally excluded from `make test-fe` because they:
- Compare screenshots pixel-by-pixel and can fail due to font rendering differences
- Require baseline updates when UI changes intentionally
- Run slower than functional tests

Run visual tests separately after intentional UI changes:
```bash
make test-fe-visual         # Run and compare against baselines
make test-fe-visual-update  # Update baselines after UI changes
```

### Writing New Tests

**Backend:**
1. Add unit tests for pure functions in `tests/unit/`
2. Add integration tests for API endpoints in `tests/integration/`
3. Use existing mock fixtures from `conftest.py` (e.g., `mock_gemini_llm`, `mock_google_tokeninfo`)
4. Never make real API calls - mock at the right level

**Frontend:**
1. Add unit tests for utilities in `web/tests/unit/`
2. Add component tests in `web/tests/components/` (use jsdom for DOM simulation)
3. Add E2E tests in `web/tests/e2e/` for user workflows
4. Use `global-setup.ts` fixtures for isolated test state
5. For mobile tests, use `test.use({ viewport: { width: 375, height: 812 } })`
6. Both batch and streaming modes are fully supported by the mock server

### E2E Test Server

The E2E test server (`tests/e2e-server.py`) is a Flask app that mocks external services:

- **Mock LLM**: Returns mock responses with proper AIMessage objects for LangGraph
- **SSE Streaming**: Custom endpoint streams tokens word-by-word via Server-Sent Events
- **Auth bypass**: `E2E_TESTING=true` skips Google auth and JWT validation
- **Database reset**: `/test/reset` endpoint clears database between tests
- **Isolated DB**: Each test run uses a unique database file

To run E2E tests manually:
```bash
# Terminal 1: Start mock server
cd web && python ../tests/e2e-server.py

# Terminal 2: Run tests
cd web && npx playwright test
```

### Visual Regression Tests

Visual tests capture screenshots and compare against baselines. Use them to verify UI changes haven't broken anything unintentionally.

```bash
make test-fe-visual           # Run visual tests against baselines
make test-fe-visual-update    # Update baselines after intentional UI changes
```

**Baseline locations:**
- `web/tests/visual/chat.visual.ts-snapshots/` - Desktop chat interface
- `web/tests/visual/mobile.visual.ts-snapshots/` - Mobile/iPad layouts

**When to run visual tests:**
- After making CSS changes
- After modifying component structure
- After changing responsive breakpoints
- Before committing UI changes (to verify no regressions)

**When to update baselines:**
- After intentional UI changes (run `make test-fe-visual-update`)
- Commit the new baseline screenshots with your UI changes

**Troubleshooting visual test failures:**
- Check `web/playwright-report/index.html` for diff images
- Ensure tests run with consistent viewport sizes
- Font rendering differences between machines can cause false failures

## Related Files

- [TODO.md](TODO.md) - Memory bank for planned work
- [README.md](README.md) - User-facing documentation

## Request Validation

The API uses Pydantic v2 for request validation. All validation follows a consistent pattern using the `@validate_request` decorator.

### Schema Location

Request schemas are defined in [schemas.py](src/api/schemas.py):
- `GoogleAuthRequest` - POST /auth/google
- `CreateConversationRequest` - POST /api/conversations
- `UpdateConversationRequest` - PATCH /api/conversations/<id>
- `ChatRequest` - POST /chat/batch and /chat/stream
- `FileAttachment` - Nested schema for file uploads

### Adding Validation to a New Endpoint

1. Define the schema in `src/api/schemas.py`:

```python
from pydantic import BaseModel, Field, field_validator

class MyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    count: int = Field(default=10, ge=1, le=100)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if v.startswith("_"):
            raise ValueError("Name cannot start with underscore")
        return v
```

2. Apply the decorator to your route:

```python
from src.api.schemas import MyRequest
from src.api.validation import validate_request
from src.db.models import User

@api.route("/endpoint", methods=["POST"])
@require_auth
@validate_request(MyRequest)
def my_endpoint(user: User, data: MyRequest) -> tuple[dict, int]:
    # user is injected by @require_auth
    # data is the validated Pydantic model from @validate_request
    name = data.name
    count = data.count
    ...
```

### Decorator Order

Decorators are applied bottom-to-top, so the order matters:
```python
@api.route("/endpoint", methods=["POST"])
@require_auth           # 2nd: checks auth, injects user
@validate_request(...)  # 1st: validates JSON, appends data after user
def handler(user: User, data: MySchema):
    ...
```

This means auth errors return before validation is attempted (correct behavior - don't validate requests from unauthenticated users). The `user` argument comes first (from `@require_auth`), followed by `data` (from `@validate_request`).

### Two-Phase File Validation

File uploads use two-phase validation:

1. **Structure (Pydantic)**: Field presence, MIME type in allowed list, file count limit
2. **Content (validate_files)**: Base64 decoding, file size limits

This allows fast-fail on structure before expensive base64 operations.

### Error Response Format

Validation errors return the standard error format:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable error message",
    "retryable": false,
    "details": {"field": "field_name"}
  }
}
```

### Key Files

- [schemas.py](src/api/schemas.py) - Pydantic schema definitions
- [validation.py](src/api/validation.py) - `@validate_request` decorator and error conversion
- [errors.py](src/api/errors.py) - Error response helpers
- [files.py](src/utils/files.py) - Content validation for files

## Error Handling

The application implements comprehensive error handling across both backend and frontend to ensure graceful failure recovery and a good user experience.

### Backend Error Responses

All API errors return a standardized JSON format from [errors.py](src/api/errors.py):

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable message",
    "retryable": false,
    "details": { "field": "email" }
  }
}
```

**Error codes** (from `ErrorCode` enum):
- `AUTH_REQUIRED`, `AUTH_INVALID`, `AUTH_EXPIRED`, `AUTH_FORBIDDEN` - Authentication errors
- `VALIDATION_ERROR`, `MISSING_FIELD`, `INVALID_FORMAT` - Input validation errors
- `NOT_FOUND`, `CONFLICT` - Resource errors
- `SERVER_ERROR`, `TIMEOUT`, `SERVICE_UNAVAILABLE`, `RATE_LIMITED` - Server errors (retryable)
- `EXTERNAL_SERVICE_ERROR`, `LLM_ERROR`, `TOOL_ERROR` - External service errors

**Helper functions** for common responses:
```python
from src.api.errors import validation_error, not_found_error, server_error

# Returns tuple of (response_dict, status_code)
return validation_error("Invalid email", field="email")  # 400
return not_found_error("Conversation")  # 404
return server_error()  # 500
```

**Safe JSON parsing** - Always use `get_request_json()` from [utils.py](src/api/utils.py):
```python
from src.api.utils import get_request_json
from src.api.errors import invalid_json_error

data = get_request_json(request)
if data is None:
    return invalid_json_error()
```

### Frontend Error Handling

#### Toast Notifications

Use [Toast.ts](web/src/components/Toast.ts) for transient error messages:
```typescript
import { toast } from './components/Toast';

toast.error('Failed to save.');
toast.error('Connection lost.', {
  action: { label: 'Retry', onClick: () => retry() }
});
toast.warning('File too large.');
toast.success('Saved!');
toast.info('Processing...');
```

- Auto-dismiss after 5 seconds by default
- Persistent if action button is provided
- Top-center positioning (doesn't interfere with input)

#### Modal Dialogs

Use [Modal.ts](web/src/components/Modal.ts) instead of native `alert()`, `confirm()`, `prompt()`:
```typescript
import { showAlert, showConfirm, showPrompt } from './components/Modal';

await showAlert({ title: 'Error', message: 'Something went wrong.' });

const confirmed = await showConfirm({
  title: 'Delete',
  message: 'Are you sure?',
  confirmLabel: 'Delete',
  danger: true
});

const value = await showPrompt({
  title: 'Rename',
  message: 'Enter new name:',
  defaultValue: 'Untitled'
});
```

#### API Client Error Handling

The [api/client.ts](web/src/api/client.ts) provides:

1. **Retry logic with exponential backoff** - Only for GET requests (idempotent)
2. **Request timeouts** - 30s default, 5 minutes for chat
3. **Streaming per-read timeout** - 60s timeout per read (backend sends keepalives every 15s)
4. **Extended ApiError class** with semantic properties:

```typescript
try {
  await someApiCall();
} catch (error) {
  if (error instanceof ApiError) {
    if (error.isTimeout) {
      toast.error('Request timed out.');
    } else if (error.isNetworkError) {
      toast.error('Network error. Check your connection.');
    } else if (error.retryable) {
      toast.error('Failed.', { action: { label: 'Retry', onClick: retry } });
    } else {
      toast.error(error.message);
    }
  }
}
```

**IMPORTANT - Retry Safety:**
- ✅ Safe to retry: GET requests (idempotent)
- ⚠️ Conditionally safe: PATCH, DELETE (idempotent operations)
- ❌ NOT safe to retry: POST (creates resources, could duplicate)

#### Draft-Based Message Recovery

When a chat message fails to send (network error, timeout, server error), the user's message and any attached files are preserved in a draft so they can retry:

**How it works:**
1. **Error occurs**: When `sendMessage()` fails (either batch or streaming mode), the catch block saves the message and files to draft state
2. **Draft saved**: `store.setDraft(message, files)` persists to Zustand store, which syncs to localStorage
3. **Toast with retry**: User sees error toast with "Retry" button
4. **Retry clicked**: `retryFromDraft()` restores message to input field, clears draft, and re-sends
5. **Success**: Draft is automatically cleared when message sends successfully

**Consistency between modes:**
- Both batch and streaming modes use the same error handling path in `sendMessage()` catch block
- Streaming errors (from SSE `error` events) are converted to `ApiError` and re-thrown
- This ensures draft saving and toast display work identically regardless of streaming mode

**Draft state in store:**
```typescript
// store.ts
draftMessage: string | null;
draftFiles: FileAttachment[];
setDraft: (message: string | null, files: FileAttachment[]) => void;
```

**Key functions in main.ts:**
- `sendMessage()` - Outer catch block saves draft and shows toast
- `sendStreamingMessage()` - Converts error events to ApiError, re-throws
- `sendBatchMessage()` - Re-throws errors to outer catch
- `retryFromDraft()` - Restores draft to input and re-sends

**Testing:**
E2E tests for retry functionality are in [chat.spec.ts](web/tests/e2e/chat.spec.ts) under "Chat - Message Retry" describe block.

### Error Handling Guidelines

**Backend:**
1. Never expose internal error details to users - log them, return generic message
2. Use `get_request_json()` for all JSON parsing (handles malformed JSON gracefully)
3. Wrap external API calls (Gemini, Google Auth) in try/except
4. Use appropriate error helpers from `errors.py`
5. Log errors with `exc_info=True` before returning error response

**Frontend:**
1. Every async operation should have error handling
2. Use toast for transient errors, modal for confirmations
3. Preserve user input on send failures (draft system in store)
4. Show retry buttons for retryable errors
5. Don't hide partial content on streaming errors

### Key Files

- [errors.py](src/api/errors.py) - Backend error response utilities
- [Toast.ts](web/src/components/Toast.ts) - Toast notification component
- [Modal.ts](web/src/components/Modal.ts) - Modal dialog component
- [api/client.ts](web/src/api/client.ts) - API client with retry/timeout
- [store.ts](web/src/state/store.ts) - Notification state, draft persistence

## Structured Logging

The application uses structured JSON logging for easy integration with Loki or other log aggregation systems. All logs include request IDs for correlation.

### Configuration

- **LOG_LEVEL**: Environment variable controlling log verbosity (default: `INFO`)
  - Valid levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
  - Set via `.env` file: `LOG_LEVEL=DEBUG`

### Log Format

All logs are JSON-formatted with the following structure:
```json
{
  "timestamp": "2024-01-01 12:00:00",
  "level": "INFO",
  "logger": "src.api.routes",
  "message": "Batch chat request",
  "request_id": "abc-123-def",
  "user_id": "user-123",
  "conversation_id": "conv-456"
}
```

### Request IDs

Every request automatically gets a unique request ID:
- Generated as UUID if not provided in `X-Request-ID` header
- Included in all log entries for that request
- Enables correlation of logs across the request lifecycle

### Logging Guidelines

**When adding new code, always add appropriate logging:**

1. **INFO level**: Important operations that happen per-request
   - Request start/completion
   - Successful authentication
   - Conversation creation/deletion
   - Chat completions

2. **DEBUG level**: Detailed information for troubleshooting
   - Function entry/exit
   - Intermediate state values
   - Payload snippets (use `log_payload_snippet()` helper)
   - Database operations

3. **WARNING level**: Unusual but recoverable situations
   - Validation failures
   - Missing optional data
   - Retryable errors

4. **ERROR level**: Failures that need attention
   - Exceptions (always use `exc_info=True`)
   - Failed operations
   - System errors

**Best Practices:**
- Use structured logging with `extra` dict for context
- Include relevant IDs (user_id, conversation_id, message_id) in logs
- Log payload snippets for debugging (but truncate large data)
- Always log exceptions with `exc_info=True`
- Use appropriate log levels - don't spam INFO with debug details

**Example:**
```python
from src.utils.logging import get_logger, log_payload_snippet

logger = get_logger(__name__)

def my_function(user_id: str, data: dict) -> None:
    logger.debug("Function called", extra={"user_id": user_id})
    log_payload_snippet(logger, data)

    try:
        # ... do work ...
        logger.info("Operation completed", extra={"user_id": user_id, "result": result})
    except Exception as e:
        logger.error("Operation failed", extra={"user_id": user_id, "error": str(e)}, exc_info=True)
        raise
```

### Key Logging Points

- **Routes**: All endpoints log request/response with status codes
- **Agent**: LLM invocations, tool calls, response extraction
- **Tools**: Tool execution start/completion, errors
- **Database**: CRUD operations, state saves
- **Auth**: Token validation, user lookups
- **File processing**: Validation, thumbnail generation

### Frontend Logging

The frontend uses a structured logging utility similar to the backend, providing consistent logging across the application.

**Configuration:**
- Log level is configured in [config.ts](web/src/config.ts) via `LOG_LEVEL`
- In development: defaults to `debug` (all logs shown)
- In production: defaults to `warn` (only warnings and errors)
- Can be overridden at runtime via `window.__LOG_LEVEL__`

**Log Levels:**
- `debug`: Detailed information for troubleshooting (dev only by default)
- `info`: Important operations and state changes
- `warn`: Unusual but recoverable situations
- `error`: Failures that need attention

**Usage:**
```typescript
import { createLogger } from './utils/logger';

const log = createLogger('my-module');

log.debug('Function called', { userId, data });
log.info('Operation completed', { result });
log.warn('Unexpected state', { state });
log.error('Operation failed', { error, context });
```

**Output:**
- Development: Colored console output with `[module-name]` prefix for readability
- Production: JSON-formatted output for log aggregation

**Key Files:**
- [logger.ts](web/src/utils/logger.ts) - Logger utility with `createLogger()` factory
- [config.ts](web/src/config.ts) - `LOG_LEVEL` configuration

**Guidelines:**
- Create a named logger per module: `const log = createLogger('module-name')`
- Use `debug` for detailed troubleshooting info (retry attempts, state changes)
- Use `info` for significant events (auth success, version banner shown)
- Use `warn` for recoverable issues (cost fetch failed, optional feature unavailable)
- Use `error` for failures that affect functionality (API errors, file read failures)
- Always include relevant context as the second argument (error objects, IDs, etc.)

## Database Performance & Monitoring

The application includes several features to optimize database performance and help diagnose issues.

### Database Indexes

The following indexes are defined to optimize common query patterns:

**Conversations table:**
- `idx_conversations_user_id` - For filtering by user
- `idx_conversations_user_id_updated_at` - Composite index for `list_conversations()` (filter + sort)

**Messages table:**
- `idx_messages_conversation_id` - For filtering by conversation
- `idx_messages_conversation_id_created_at` - Composite index for `get_messages()` (filter + sort)

**Message costs table:**
- `idx_message_costs_message_id` - For cost lookups by message
- `idx_message_costs_conversation_id` - For conversation cost totals
- `idx_message_costs_user_id` - For user cost queries
- `idx_message_costs_created_at` - For date-based queries

### Slow Query Logging

In development/debug mode, the database tracks query execution time and logs warnings for slow queries.

**Configuration:**
- `SLOW_QUERY_THRESHOLD_MS`: Threshold in milliseconds (default: 100)
- Enabled when `LOG_LEVEL=DEBUG` or `FLASK_ENV=development`

**Log output:**
```json
{
  "level": "WARNING",
  "message": "Slow query detected",
  "query_snippet": "SELECT * FROM conversations WHERE user_id = ? ORDER BY...",
  "params_snippet": "('user-123-abc',)",
  "elapsed_ms": 150.5,
  "threshold_ms": 100
}
```

**Security considerations:**
- Query text is truncated to 200 characters
- Parameters are truncated to 100 characters (to avoid logging large base64 file data)

### Database Connectivity Check

At startup, the application verifies database connectivity before starting the Flask app.

**Checks performed:**
1. Parent directory exists
2. Parent directory is writable
3. Database file is readable/writable (if exists)
4. Can connect and execute `SELECT 1`

**Error handling:**
- Missing directory: Clear message about missing directory
- Permission errors: Guidance on file/directory permissions
- Database locked: Indicates another process is using it
- Disk I/O errors: Suggests checking disk health

**Key files:**
- [models.py](src/db/models.py) - `check_database_connectivity()`, `_execute_with_timing()`
- [app.py](src/app.py) - Startup connectivity check in `main()`
- [config.py](src/config.py) - `SLOW_QUERY_THRESHOLD_MS` setting

### Database Best Practices

When adding or modifying database code, follow these guidelines:

**Avoiding N+1 Queries:**
- Never query inside a loop - fetch all needed data in a single query
- Use JOINs or subqueries when you need related data
- If you need to load a list of items with counts/aggregates, use a single query with GROUP BY

```python
# BAD - N+1 pattern (1 query + N queries)
conversations = db.list_conversations(user_id)
for conv in conversations:
    count = db.get_message_count(conv.id)  # N queries!

# GOOD - Single query with JOIN or subquery
conversations = db.list_conversations_with_counts(user_id)  # 1 query
```

**When to Add Indexes:**
- Add indexes on columns used in WHERE clauses (e.g., `user_id`, `conversation_id`)
- Add composite indexes for queries that filter AND sort (e.g., `(user_id, updated_at DESC)`)
- Primary keys and UNIQUE constraints already have indexes
- Don't over-index - each index slows down INSERT/UPDATE operations

**Index Naming Convention:**
```sql
-- Single column: idx_{table}_{column}
CREATE INDEX idx_conversations_user_id ON conversations(user_id)

-- Composite: idx_{table}_{col1}_{col2}
CREATE INDEX idx_conversations_user_id_updated_at ON conversations(user_id, updated_at DESC)
```

**Query Patterns in This Codebase:**
- All queries go through `_execute_with_timing()` for automatic slow query detection
- Use parameterized queries (`?` placeholders) - never string concatenation
- Keep queries in [models.py](src/db/models.py) - don't write SQL in routes
- Return dataclasses (`User`, `Conversation`, `Message`) from database methods

**Migration Guidelines:**
- Create new migration files in `migrations/` directory (numbered sequentially)
- Use `IF NOT EXISTS` / `IF EXISTS` for safe rollbacks
- Follow pattern from existing migrations (see [0005_add_cost_tracking.py](migrations/0005_add_cost_tracking.py))
- Test migrations on a copy of production data before deploying

## PWA Viewport Height Fix

The app uses a specific layout approach to ensure the sidebar and main panel fill 100% of the screen height in PWA mode (no address bar, full screen).

### The Problem

Initially, the app had gaps at the bottom of the sidebar and main panel, especially when the keyboard opened/closed. Various approaches were tried (JavaScript viewport fixes, `100vh`, `100dvh`, `100svh`, explicit heights) but none worked reliably.

### The Solution

The final working solution uses:
1. **Root container**: `#app` with `position: fixed; inset: 0` - this naturally fills the viewport without needing explicit height
2. **Flex children**: Sidebar and main panel use `align-self: stretch` (default flexbox behavior) to fill the container height
3. **No explicit heights**: Avoid `height: 100%` or `height: 100vh` on flex children - let flexbox handle it

### Key Implementation Details

```css
#app {
    display: flex;
    position: fixed;
    inset: 0;  /* Fills viewport naturally */
    overflow: hidden;
}

.sidebar {
    display: flex;
    flex-direction: column;
    align-self: stretch;  /* Fills parent height */
    /* No explicit height needed */
}

.main {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-self: stretch;  /* Fills parent height */
    /* No explicit height needed */
}
```

### Why This Works

- `position: fixed; inset: 0` makes `#app` fill the viewport regardless of parent height
- Flexbox's default `align-items: stretch` (on flex container) makes children fill cross-axis (height)
- No JavaScript needed - pure CSS solution
- Works consistently in PWA mode where there's no address bar

### Layout Jump Prevention

The conversation cost display below the input area has `min-height: 16px` and is never hidden (no `:empty { display: none }`). This prevents layout jumping when the cost updates or when switching between conversations with/without costs.

**Key files:**
- [main.css](web/src/styles/main.css) - Layout structure and conversation cost display styling

## Documentation Maintenance

When making significant changes to the codebase:
1. Update [README.md](README.md) if user-facing features change
2. Update this file (AGENTS.md) if architecture, code patterns, or developer workflows change
3. Update [TODO.md](TODO.md) to mark completed items or add new planned work

**Important**: When implementing a new feature, always update documentation as part of the commit - don't wait to be asked. For significant features, add a dedicated section to AGENTS.md explaining how it works, key files, and any testing/debugging tips.

**When adding new code, always add appropriate logging** - see the Structured Logging section above for guidelines.

---

## Preferences & Corrections

When I correct Claude's approach, the reasoning is documented here to prevent repeated mistakes.

### Naming

**Preference**: Use "AI Chatbot" consistently (not "AI Chat")
**Context**: Branding consistency across all UI text, meta tags, and documentation

### Directory Structure

**Preference**: Use `web/` for frontend (not `frontend/`)
**Context**: Leaves room for potential native mobile app later (`ios/`, `android/`)

### State Management

**Preference**: Use Zustand for state management
**Context**: Lightweight, TypeScript-first, simpler than Redux. Avoid custom state management solutions.

### Development Server

**Preference**: Use `concurrently` for running multiple dev servers
**Context**: Background processes are hard to manage. `concurrently` shows both outputs clearly and kills both on Ctrl+C.
**Avoid**: Using `&` or background jobs in Makefile

### UI Patterns

**Preference**: Use event delegation for dynamic elements
**Context**: iOS Safari has issues with inline onclick handlers on dynamically created elements
**Avoid**: Inline `onclick` attributes in template strings

### innerHTML Usage

**Preference**: Minimize innerHTML usage; use `textContent`, `createElement`, or DOM helpers where possible
**Context**: innerHTML parses HTML and can be a security risk if misused. Using DOM methods is more explicit about intent.

**When innerHTML is ACCEPTABLE:**
- Setting SVG icons from [icons.ts](web/src/utils/icons.ts) (SVG markup must be rendered as HTML)
- Rendering markdown content from `renderMarkdown()` (returns sanitized HTML)
- Complex HTML structures that would be cumbersome to build with createElement (e.g., app shell, modals)
- Any content that legitimately needs HTML markup (line breaks as `<br>`, styled elements)

**When to AVOID innerHTML:**
- Clearing element content → Use `clearElement(element)` from [dom.ts](web/src/utils/dom.ts)
- Setting plain text → Use `element.textContent = text`
- Building simple lists → Consider `createElement` with loops

**Security requirements:**
- ALWAYS use `escapeHtml()` for any user-controlled content before interpolating into innerHTML
- SVG icons from icons.ts are safe (static constants, not user input)
- Markdown is rendered through marked.js which handles sanitization

**Key helpers in [dom.ts](web/src/utils/dom.ts):**
- `clearElement(element)` - Clear all content (preferred over `innerHTML = ''`)
- `createElement(tag, attrs, children)` - Build elements programmatically
- `escapeHtml(text)` - Escape HTML special characters for safe interpolation

### Icons

**Preference**: Centralize SVG icons in [icons.ts](web/src/utils/icons.ts)
**Context**: Prevents duplication across components, makes icons easy to find and update
**Avoid**: Inline SVG in template strings (import from icons.ts instead)

### Constants

**Preference**: Use `DEFAULT_CONVERSATION_TITLE` constant from [api.ts](web/src/types/api.ts)
**Context**: Avoids magic strings scattered across the codebase
**Avoid**: Hardcoding `'New Conversation'` directly in code

### Conversation Creation

**Pattern**: Lazy conversation creation - conversations are created locally with a `temp-` prefixed ID, only persisted to DB on first message
**Location**: [main.ts](web/src/main.ts) - `createConversation()`, `sendMessage()`, `isTempConversation()`
**Rationale**: Prevents empty conversations from polluting the database when users click "New Chat" but don't send any messages

### Concurrent Request Handling

The app supports multiple active requests across different conversations simultaneously. Requests continue processing in the background even when users switch conversations or disconnect.

**Client-side behavior:**
- **Request tracking**: Active requests are tracked per conversation in `activeRequests` map in [main.ts](web/src/main.ts)
- **Conversation switching**: When switching conversations, active requests are NOT cancelled - they continue in the background
- **UI updates**: Requests only update the UI if their conversation is still the current conversation. If the user switched away, the request completes silently and the message is saved to the database
- **Error handling**: Errors are only shown to the user if the conversation is still current when the error occurs

**Server-side behavior:**
- **Client disconnection detection**: Streaming generator catches `BrokenPipeError`, `ConnectionError`, and `OSError` when yielding to detect client disconnections
- **Background completion**: Background thread continues processing even if client disconnects. A cleanup thread ensures the message is saved to the database even if the generator stops early
- **Message persistence**: Both streaming and batch requests save messages to the database before returning responses, ensuring data is never lost even if the client disconnects

**Key implementation details:**
- **Streaming**: Background thread (`stream_tokens`) processes LLM tokens and stores final results. Cleanup thread monitors completion and saves message if generator stopped early
- **Batch**: Message is saved before returning response, so disconnection doesn't affect persistence
- **Request tracking**: Client tracks requests with unique IDs (`stream-{convId}-{timestamp}` or `batch-{convId}-{timestamp}`) to allow multiple concurrent requests

**When adding new request types:**
1. Track requests in `activeRequests` map with unique IDs
2. Check `isCurrentConversation` before updating UI
3. Clean up request tracking in `finally` blocks
4. On server, ensure operations complete even if client disconnects (catch disconnection errors, use cleanup threads if needed)

**Key files:**
- [main.ts](web/src/main.ts) - Request tracking, conversation switching logic, UI update guards
- [routes.py](src/api/routes.py) - Client disconnection detection, cleanup threads, message persistence

### @require_auth Injects User

The `@require_auth` decorator injects the authenticated `User` as the first argument to route handlers. This eliminates the need for `get_current_user()` calls and makes the contract explicit in the function signature.

**Pattern:**
```python
@api.route("/endpoint", methods=["GET"])
@require_auth
def my_endpoint(user: User) -> dict:
    # user is guaranteed to be a valid User - decorator handles auth errors
    return {"user_id": user.id}
```

**With `@validate_request`:**
When combined with `@validate_request`, user comes first, then validated data:
```python
@api.route("/endpoint", methods=["POST"])
@require_auth
@validate_request(MySchema)
def my_endpoint(user: User, data: MySchema) -> dict:
    # user from @require_auth, data from @validate_request
    return {"user_id": user.id, "value": data.value}
```

**Key files:**
- [jwt_auth.py](src/auth/jwt_auth.py) - `@require_auth` decorator injects user
- [validation.py](src/api/validation.py) - `@validate_request` appends validated data after user
- [routes.py](src/api/routes.py) - All routes follow this pattern
