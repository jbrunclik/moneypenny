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
- [x] **Show thinking/tool details** - Display model reasoning and tool execution behind a toggle
- [ ] **Configurable thinking level** - Allow user to select thinking level (low/medium/high) in UI
- [ ] **Stop generation button** - Send button turns into stop button during streaming to cancel generation
- [ ] Improve error handling and user feedback
- [x] **Add loading states and animations** - Conversation loading spinner, thumbnail loading indicators
- [x] Conversation delete functionality
- [ ] Conversation rename functionality
- [x] Mobile gesture support (swipe to open sidebar, swipe to delete conversations)
- [x] **Show message timestamps** - Display message timestamps on hover (locale-aware formatting)
- [x] **Scroll to bottom button** - Floating button to jump to latest messages when scrolled up
- [ ] **Version update banner** - Show banner to user when new version is available, prompting to reload the page

## Phase 3 - Tools & Extensions
- [x] **Tool framework** - Extensible system for adding agent tools
- [x] Web search tool (DuckDuckGo)
- [x] URL fetch tool (extract text from web pages)
- [x] **Forcing search/browser tool** - Allow users to force the agent to use search or browser tools for specific queries
- [ ] **Show internet sources** - Display sources/links from web_search and fetch_url tools in a user-friendly format
- [ ] Image generation tool (Gemini 3 Pro Image or Imagen)
- [ ] Text-to-speech tool
- [ ] Code execution sandbox
- [x] File upload and processing (images, PDFs, text files)
- [x] **Image thumbnails & lightbox** - Thumbnails in chat, click to view full-size with on-demand loading
- [x] **Performance optimizations** - Optimized conversation payload (metadata only), parallel thumbnail fetching

## Phase 4 - Advanced Features
- [ ] Multiple AI providers (Anthropic Claude, OpenAI)
- [ ] Custom system prompts per conversation
- [ ] Conversation export (JSON, Markdown)
- [ ] Conversation sharing (public links)
- [ ] Keyboard shortcuts
- [x] Voice input (speech-to-text using Web Speech API)
- [ ] **Voice conversation mode** - Full voice-based conversation with speech-to-text input and text-to-speech output

## Phase 5 - Production Hardening
- [ ] Comprehensive test suite
- [ ] Rate limiting
- [ ] Request logging and monitoring
- [x] Database migrations system (yoyo-migrations)
- [ ] **Cost tracking** - Track API costs per user and per conversation
- [ ] Backup and restore
- [ ] Docker deployment option

## CI/CD & DevOps
- [ ] **GitHub Actions** - Workflow for linting (ruff, mypy) on PRs
- [ ] **Dependabot** - Configuration for automated dependency updates
- [ ] Docker image and docker-compose setup

## Technical Debt

### 🔴 Critical / High Priority
- [ ] **Replace assert statements with proper error handling** - `routes.py` uses `assert user is not None` after `@require_auth` which can be disabled with Python `-O` flag. Replace with explicit error responses.
- [ ] **Add comprehensive test suite** - No tests exist. Create `tests/` directory with unit, integration, and e2e tests for auth, API, agent, and frontend.
- [ ] **Catch specific exceptions** - Multiple bare `except Exception:` handlers in `chat_agent.py`, `routes.py`, and `images.py`. Catch specific exceptions instead.

### 🟠 Security
- [ ] **Add server-side file type validation** - File upload relies on client MIME type. Add magic bytes verification using `python-magic`.
- [ ] **Add request size limits** - Enforce request body size limits in Flask to prevent DoS
- [ ] **Improve JWT token handling** - Add token refresh mechanism instead of fixed expiration; consider enforcing minimum secret length (32+ chars)
- [ ] **Add CORS configuration** - Explicitly configure CORS if needed for cross-origin requests

### 🟡 Code Quality
- [x] Add proper database migrations (yoyo-migrations)
- [ ] Add request validation (pydantic or marshmallow)
- [ ] Consider async Flask (quart) for better concurrency
- [ ] Add OpenAPI/Swagger documentation
- [ ] **Store files and thumbnails outside DB** - Move file data and thumbnails to object storage (S3, MinIO, etc.) for better scalability and performance
- [x] **Split JavaScript into modules** - Migrated to Vite + TypeScript with modular components in `web/src/`
- [ ] **Add structured logging** - Replace print statements with proper logging framework (Python logging module). Currently `images.py:69` uses `print()`.
- [ ] **Error handling standardization** - Create consistent error response format across all API endpoints
- [ ] **Frontend error boundaries** - Add error handling for failed API calls with retry logic. Also wrap `response.json()` in try-catch.
- [x] **Remove inline onclick handlers** - Migrated to event delegation in TypeScript components
- [ ] **Add request timeout handling** - Handle timeouts for long-running Gemini API calls gracefully
- [x] **TypeScript migration** - Frontend migrated to TypeScript with strict mode
- [ ] **Extract magic numbers and strings to constants** - Swipe thresholds, timeouts extracted to named constants in TypeScript
- [ ] **Remove console.log statements** - Implement structured frontend logging (console statements remain for debugging)
- [ ] **Reduce innerHTML usage** - Heavy reliance on innerHTML; prefer textContent and createElement where possible
- [ ] **Audit unused CSS classes** - After TypeScript migration, review and remove unused CSS classes from main.css

### 🟢 Database
- [ ] **Database connection pooling** - Consider connection pooling for SQLite (though SQLite has limitations)
- [ ] **Add database indexes** - Add indexes on frequently queried columns (conversations.user_id, messages.conversation_id, etc.)
- [ ] **Add database query optimization** - Review and optimize N+1 query patterns (e.g., loading conversations with message counts)
- [ ] **Pagination for conversations** - Add pagination to conversations list endpoint for users with many conversations
- [ ] **Add database backup automation** - Automated daily backups of SQLite database
- [ ] **Add database vacuum** - Periodic SQLite VACUUM to reclaim space and optimize database
- [ ] **Add database query logging** - Log slow queries for optimization (in development/debug mode)
- [ ] **Add database connectivity check** - Verify database is accessible at startup with clear error message

### 🔵 Frontend Performance & UX
- [ ] **Replace native browser dialogs** - Replace `alert()`, `confirm()`, and `prompt()` with custom modal components for better UX
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
- [ ] **Environment variable validation** - Validate all required env vars at startup with clear error messages
- [ ] **Add health check endpoint** - `/health` endpoint for monitoring and load balancer checks
- [ ] **Add request/response logging middleware** - Log all API requests and responses (with sensitive data redaction)
- [ ] **Add request ID tracking** - Include request IDs in logs and error responses for easier debugging
- [ ] **Add API response compression** - Enable gzip compression for API responses
- [ ] **Remove unused dependencies** - Audit and remove any unused npm/Python dependencies
- [ ] **Optimize image processing** - Consider async/background processing for thumbnail generation on large images
- [ ] **Make HTTP timeout configurable** - `tools.py` has hardcoded 30s timeout; move to config
- [ ] **Make thumbnail dimensions configurable** - `images.py` has hardcoded 400x400; move to config

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
