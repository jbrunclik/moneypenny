# AI Chatbot - TODO / Memory Bank

This file tracks planned features, improvements, and technical debt.

## Phase 1 - MVP (Current)
- [x] Project structure and configuration
- [x] Flask backend with Gemini integration
- [x] SQLite chat storage
- [x] Google Sign In with email whitelist
- [x] Basic dark theme UI
- [x] Model selection (Pro/Flash)
- [x] Markdown rendering

## Phase 2 - Streaming & Polish
- [x] **Streaming responses** - Display tokens as they arrive from Gemini (with toggle)
- [x] **Show thinking/tool details** - Display model thinking and tool execution trace during streaming with auto-collapse to "Show details" toggle. Shows search queries, URLs, and image prompts with markdown formatting
- [x] **Improve error handling and user feedback** - Toast notifications, custom modals, retry logic, draft message preservation
- [x] **Add loading states and animations** - Conversation loading spinner, thumbnail loading indicators
- [x] Conversation delete functionality
- [x] **Conversation rename functionality** - Rename via pencil icon on hover (desktop) or swipe actions (mobile). Updates sidebar and chat header in real-time
- [x] Mobile gesture support (swipe to open sidebar, swipe to delete conversations)
- [x] **Show message timestamps** - Display message timestamps on hover (locale-aware formatting)
- [x] **Scroll to bottom button** - Floating button to jump to latest messages when scrolled up
- [x] **Version update banner** - Show banner to user when new version is available, prompting to reload the page
- [x] **Stop button for streaming** - Transform send button into stop button during streaming to allow interrupting responses. Button changes to red square icon, clicking aborts the stream and removes the streaming message from UI. Note: Partial messages may remain in backend database (see message delete button TODO)
- [ ] **Message delete button** - Add delete button to message actions (three-dot menu) to allow users to delete individual messages. Useful for cleaning up partial messages from aborted streams or removing unwanted messages
- [ ] **Thinking mode toggle** - Allow enabling Gemini thinking mode with configurable level (minimal/low/medium/high) using long-press UI similar to voice input language selector
- [x] **Show search sources** - Display internet sources used by web_search tool in a popup accessible via message actions button

## Phase 3 - Tools & Extensions
- [x] **Tool framework** - Extensible system for adding agent tools
- [x] Web search tool (DuckDuckGo)
- [x] URL fetch tool (extract text from web pages)
- [x] **Forcing search/browser tool** - Allow users to force the agent to use search or browser tools for specific queries
- [x] Image generation tool (Gemini 3 Pro Image Preview)
- [ ] Text-to-speech tool
- [x] **Code execution sandbox** - Secure Python sandbox using llm-sandbox with Docker. No network access, configurable resource limits. Supports file output (PDFs, images), matplotlib plots. See CLAUDE.md "Code Execution Sandbox" section.
- [x] File upload and processing (images, PDFs, text files)
- [x] **Image thumbnails & lightbox** - Thumbnails in chat, click to view full-size with on-demand loading
- [x] **Performance optimizations** - Optimized conversation payload (metadata only), parallel thumbnail fetching

## Phase 4 - Advanced Features
- [ ] Multiple AI providers (Anthropic Claude, OpenAI)
- [ ] Custom system prompts per conversation
- [x] **User memory** - LLM extracts interesting facts about the user and stores them in database. Memories are categorized (preference, fact, context, goal) and injected into system prompt for personalization. LLM can add/update/delete memories via metadata operations. Users can view memories via brain icon button in sidebar and delete with confirmation dialog. 100 memory limit with LLM-managed consolidation. See `src/agent/chat_agent.py` for `MEMORY_SYSTEM_PROMPT` and `get_user_memories_prompt()`, `web/src/components/MemoriesPopup.ts` for UI.
- [x] **System prompt customization** - Custom instructions feature allows users to customize LLM behavior via free-text textarea in settings popup (accessible from sidebar). 2000 character limit, instructions are injected into system prompt. See `CUSTOM_INSTRUCTIONS_PROMPT` in `chat_agent.py` and `SettingsPopup.ts` for UI.
- [ ] Conversation export (JSON, Markdown)
- [ ] Conversation sharing (public links)
- [ ] Keyboard shortcuts
- [x] Voice input (speech-to-text using Web Speech API)
- [ ] **Voice conversation mode** - Full voice-based conversation with speech-to-text input and text-to-speech output

## Phase 5 - Production Hardening
- [x] Backend test suite (pytest with unit and integration tests)
- [x] Frontend test suite (Vitest unit/component tests + Playwright E2E tests)
- [ ] Rate limiting
- [x] Request logging and monitoring
- [x] Database migrations system (yoyo-migrations)
- [x] **Cost tracking** - Track API costs per user and per conversation
- [x] **Automated currency rate updates** - Daily systemd timer fetches rates from open.er-api.com (free API), stores in DB. See "Currency Rate Updates" section in CLAUDE.md.
- [ ] Backup and restore
- [ ] Docker deployment option

## CI/CD & DevOps
- [x] **GitHub Actions** - Workflow for linting and testing on PRs (runs backend + frontend tests)
- [x] **Dependabot** - Configuration for automated dependency updates (pip, npm, github-actions)
- [ ] Docker image and docker-compose setup

## Technical Debt

### 🔴 Connection Resilience (Slow/Unreliable Networks)
- [x] **Save streaming responses on connection failure** - Implemented via cleanup thread that saves message to DB even if client disconnects mid-stream. See `cleanup_and_save()` in routes.py.
- [x] **Push title updates in streaming `done` event** - The `done` SSE event now includes `title` field when a title is auto-generated. Client uses title directly from response, falling back to API call only if not present.
- [x] **Add retry logic for failed API calls** - Frontend automatically retries GET requests with exponential backoff. POST requests show toast with manual retry button.
- [ ] **Detect and handle offline state** - Show offline indicator when network is unavailable. Queue messages locally and sync when connection returns.
- [ ] **Handle partial file uploads** - Large file uploads can fail mid-transfer. Consider chunked uploads with resume capability, or at minimum show clear error and allow retry.
- [ ] **Add connection quality indicator** - Show visual feedback when connection is slow (e.g., SSE keepalives arriving but no tokens for extended period).
- [x] **Handle stale JWT on reconnect** - Frontend detects `AUTH_EXPIRED` error code and shows toast prompting re-login instead of failing silently.
- [x] **Persist unsent messages locally** - Draft messages preserved in store and restored on send failure.
- [x] **Real-time data synchronization** - Implemented timestamp-based polling sync (60s interval) via SyncManager. Shows unread badges on conversations, "New messages available" banner when current conversation has updates. Handles race conditions (concurrent sync lock, streaming protection). Chose polling over SSE/WebSockets for simplicity - appropriate for single-user app. See [SyncManager.ts](web/src/sync/SyncManager.ts) and `/api/conversations/sync` endpoint. Note: Unread counts may be temporarily inaccurate if sync happens mid-message-exchange (timing race), but corrects on next sync cycle.

### 🔴 Critical / High Priority
- [x] **Refactor @require_auth to inject user** - `@require_auth` decorator now injects the authenticated `User` as the first argument to route handlers. `@validate_request` appends validated data after user. No more `get_current_user()` + assert pattern.
- [x] **Add backend test suite** - Created `tests/` directory with unit and integration tests covering auth, API routes, database, tools, and utilities.
- [x] **Add frontend test suite** - Created `web/tests/` with Vitest (unit/component) and Playwright (E2E/visual) tests. Mock server for E2E tests in `tests/e2e-server.py`.
- [x] **Catch specific exceptions** - Replaced bare `except Exception:` with specific exceptions (`binascii.Error`, `DDGSException`, `genai_errors.ClientError`, etc.) where appropriate. Kept broad handlers only for top-level error recovery (streaming threads, request handlers).

### 🟠 Security
- [x] **Add server-side file type validation** - File upload validates content via magic bytes (python-magic). Prevents MIME type spoofing for images/PDF. Text-based formats (text/plain, json, csv, markdown) skip magic validation as libmagic detection is unreliable for these.
- [ ] **Add request size limits** - Enforce request body size limits in Flask to prevent DoS
- [x] **Improve JWT token handling** - Added token refresh mechanism (proactive refresh when 2 days remain) and enforced minimum secret length (32+ chars in production)
- [ ] **Add CORS configuration** - Explicitly configure CORS if needed for cross-origin requests

### 🟡 Code Quality
- [x] Add proper database migrations (yoyo-migrations)
- [x] Add request validation (pydantic or marshmallow) - Implemented Pydantic v2 with `@validate_request` decorator
- [ ] Consider async Flask (quart) for better concurrency
- [x] **Add OpenAPI/Swagger documentation** - APIFlask generates OpenAPI 3.0 spec at `/api/openapi.json` with Swagger UI at `/api/docs`. Response schemas defined in `schemas.py` with `@api.output()` decorators. TypeScript types auto-generated via `openapi-typescript`. See "OpenAPI Documentation" section in CLAUDE.md.
- [x] **Store files and thumbnails outside DB** - Moved to separate SQLite blob store (`files.db`) for better performance. See [Blob Storage](CLAUDE.md#blob-storage) section
- [x] **Split JavaScript into modules** - Migrated to Vite + TypeScript with modular components in `web/src/`
- [x] **Add structured logging** - Replace print statements with proper logging framework (Python logging module). Currently `images.py:69` uses `print()`.
- [x] **Error handling standardization** - Consistent error response format with ErrorCode enum, retryable flag, and structured responses across all API endpoints
- [x] **Frontend error boundaries** - ApiError class with error categorization, retry logic for GET requests, toast notifications for all API errors
- [x] **Remove inline onclick handlers** - Migrated to event delegation in TypeScript components
- [x] **Add request timeout handling** - CHAT_TIMEOUT (5 min) for batch requests, DEFAULT_TIMEOUT (30s) for other requests. Streaming needs per-read timeout (TODO).
- [x] **TypeScript migration** - Frontend migrated to TypeScript with strict mode
- [x] **Extract magic numbers and strings to constants** - Created centralized `constants.{ts,py}` for unit conversions and `config.{ts,py}` for developer-configurable values. See CLAUDE.md "Constants and Configuration" section for guidelines.
- [x] **Remove console.log statements** - Implemented structured frontend logging in `web/src/utils/logger.ts` with `createLogger()` factory. All console statements replaced with structured logs. See CLAUDE.md "Frontend Logging" section.
- [x] **Reduce innerHTML usage** - Added `clearElement()` helper to replace `innerHTML = ''`. Documented acceptable vs avoidable innerHTML patterns in AGENTS.md. Remaining innerHTML uses are legitimate (SVG icons, markdown rendering, complex HTML structures).
- [x] **Audit unused CSS classes** - Removed unused classes (.settings-toggle, .toggle-*, .btn-google, .model-options, .btn-attach) after TypeScript migration
- [x] **Create design system / color palette** - Consolidated colors into variables.css with semantic naming (--color-neutral-*, --color-brand-*, --color-success-*, etc.). Split CSS into modular files: variables.css, base.css, layout.css, components/*.css. See "CSS Architecture" section in CLAUDE.md.

### 🟢 Database
- [x] **Add database indexes** - Add indexes on frequently queried columns (conversations.user_id, messages.conversation_id, etc.)
- [x] **Add database query optimization** - Review and optimize N+1 query patterns (e.g., loading conversations with message counts) - Reviewed, no N+1 patterns found
- [ ] **Pagination for conversations** - Add pagination to conversations list endpoint for users with many conversations
- [ ] **Add database backup automation** - Automated daily backups of SQLite database
- [x] **Add database vacuum** - Weekly systemd timer runs VACUUM on both databases. See "Database Vacuum" section in CLAUDE.md.
- [x] **Add database query logging** - Log slow queries for optimization (in development/debug mode)
- [x] **Add database connectivity check** - Verify database is accessible at startup with clear error message

### 🔵 Frontend Performance & UX
- [x] **Allow switching conversations without interrupting active requests/SSE** - Requests continue in background when switching conversations. UI guards with `isCurrentConversation` checks prevent updates to wrong conversation. See "Concurrent Request Handling" in CLAUDE.md.
- [ ] **iPad Safari keyboard bar gap** - When focusing input on iPad with external keyboard, the system keyboard accessory bar pushes content up, revealing a gap below the app. CSS cannot paint outside the viewport iOS reveals. Need to investigate workarounds.
- [x] **Replace native browser dialogs** - Custom Modal component (showAlert, showConfirm, showPrompt) replaces all native dialogs. Toast notifications for transient messages.
- [x] **Frontend bundle optimization** - Migrated to Vite, bundles marked.js and highlight.js from npm
- [ ] **Add service worker** - Implement service worker for offline support and better caching
- [ ] **Add file upload progress** - Show upload progress indicator for large file uploads
- [ ] **Accessibility improvements** - Add ARIA labels, improve keyboard navigation, ensure screen reader compatibility
- [x] **Frontend state management** - Migrated to Zustand for state management
- [ ] **Frontend code splitting** - Split frontend code into chunks for better initial load performance
- [ ] **Frontend error reporting** - Add error reporting service (Sentry, Rollbar) for production error tracking
- [ ] **Frontend performance monitoring** - Add performance monitoring (Web Vitals, custom metrics)
- [ ] **Frontend bundle analysis** - Analyze bundle size and identify optimization opportunities

### ⚙️ Configuration & Operations
- [x] **Environment variable validation** - Validate all required env vars at startup with clear error messages
- [x] **Add health check endpoint** - `/api/health` (liveness) and `/api/ready` (readiness) endpoints for monitoring and load balancer checks
- [x] **Add request/response logging middleware** - Log all API requests and responses (with sensitive data redaction)
- [x] **Add request ID tracking** - Include request IDs in logs and error responses for easier debugging
- [x] **Add API response compression** - Enable gzip compression via nginx (see README deployment section)
- [ ] **Remove unused dependencies** - Audit and remove any unused npm/Python dependencies
- [x] **Optimize image processing** - Background thumbnail generation using ThreadPoolExecutor, skip small images (<100KB), BILINEAR resampling for speed. Frontend polls with exponential backoff when thumbnails are pending. Lazy recovery regenerates thumbnails if pending >60s (server death recovery). See "Background Thumbnail Generation" section in CLAUDE.md.
- [x] **Make HTTP timeout configurable** - `tools.py` uses `Config.TOOL_TIMEOUT` (default 90s)
- [x] **Make thumbnail dimensions configurable** - `Config.THUMBNAIL_MAX_SIZE` (default 400x400) and `Config.THUMBNAIL_QUALITY` (default 85)

## Notes

### Gemini API Data Privacy
- Logs are NOT used for training by default on billing-enabled projects
- Logs auto-expire after 55 days
- No explicit opt-out parameter, but data sharing requires explicit opt-in

### Model IDs (as of Dec 2025)
- `gemini-3-pro-preview` - Best for complex reasoning
- `gemini-3-flash-preview` - Faster and cheaper

### Thinking Level Parameter
Gemini 3 uses `thinking_level` instead of `thinking_budget`:
- `minimal` - Fastest, least reasoning
- `low` - Good for simple tasks
- `medium` - Balanced
- `high` - Maximum reasoning depth (default)
