# Moneypenny

[![CI](https://github.com/jbrunclik/moneypenny/actions/workflows/test.yml/badge.svg)](https://github.com/jbrunclik/moneypenny/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A personal, self-hosted AI assistant built on Google Gemini. Chat is the entry point,
but it also runs a planner over your tasks and calendar, coaches training programs,
teaches languages, and executes autonomous agents on a schedule.

Built for a household of a few users, deployed on a single box.

**[Features](#features)** · **[Quick Start](#quick-start)** ·
**[Documentation](docs/README.md)** · **[Commands](#commands)**

<p align="center">
  <img src="web/tests/visual/chat.visual.ts-snapshots/conversation-with-messages-chromium-darwin.png" alt="Desktop chat interface" width="840">
  <br><em>Streaming chat with live syntax highlighting, markdown, and an expandable trace of the model's thinking and tool calls</em>
</p>

<p align="center"><sub>Every screenshot in this README is a visual-regression baseline from the test suite - they cannot drift from the real UI.</sub></p>

---

## Features

### Chat & AI
- Two models: **Gemini 3.6 Flash** ("Fast", the default) and **Gemini 3.1 Pro** ("Advanced") - switchable per conversation
- **Streaming responses**: token-by-token display (toggleable) with a thinking indicator that shows model reasoning and live tool activity
- **Resumable streams**: a dropped connection reconnects and replays the response from a server-side journal instead of losing it
- **Stop streaming**: abort mid-generation; **regenerate**, **continue**, or **edit & resend** any turn afterwards
- **Self-correcting tools**: on a tool failure the model reads the error and retries differently, up to a configurable limit
- **Long-chat compaction**: older turns are summarized non-destructively so long conversations stay affordable without losing history
- **Prompt caching**: the static system prompt and tool definitions live in Gemini's context cache
- Markdown rendering with **live syntax highlighting while the response streams**, KaTeX math, tables and code blocks with one-click copy

### Tools & Capabilities
- **File uploads**: images, videos, PDFs, and text files with multimodal analysis; screenshots paste straight from the clipboard, and images are compressed client-side before upload
- **Image generation**: create images from text, or edit an uploaded one; thumbnails open a gallery lightbox with pinch zoom, pan, fullscreen, and download, and PDFs open in an inline viewer
- **Web tools**: quota-aware web search that routes across providers (Brave -> Tavily -> Exa, DuckDuckGo as the free fallback) with per-billing-period usage ledgers, URL fetching with source citations, and full browser automation - JS rendering, clicks, form filling, screenshots (Playwright)
- **Code execution**: Python in a sandboxed Docker container for calculations, data analysis, charts, and PDFs
- **Conversation recall**: the assistant can search and read your past conversations, so "what did we decide about X?" does not depend on it having memorized X
- **Todoist**: list, add, complete, prioritize, and organize tasks across projects
- **Google Calendar**: schedule meetings and focus blocks, update events, RSVP
- **Garmin Connect**: steps, sleep, heart rate, HRV, SpO2, training readiness, activities
- **WhatsApp**: outbound notifications from autonomous agents
- **Key-value storage**: durable structured state for agents and program conversations

### Autonomous Agents
- **Scheduled execution**: cron-scheduled agents that run unattended
- **Command Center**: every agent, pending approval, and recent run in one dashboard
- **Approval workflow**: destructive actions are blocked in code until you approve them - not merely discouraged in the prompt
- **Tool permissions**: per-agent allowlists. Capabilities that outlive the run, such as writing to long-term memory, must be granted explicitly
- **Agent-to-agent**: agents can trigger other agents for multi-step workflows
- **Dedicated conversations**: each agent has its own conversation and history

<p align="center">
  <img src="web/tests/visual/agents.visual.ts-snapshots/command-center-with-approvals-chromium-darwin.png" alt="Agent command center with pending approvals" width="620">
  <br><em>Destructive actions wait for approval, showing the exact tool and arguments</em>
</p>

### Planner Dashboard
- **Unified schedule**: Todoist tasks and Calendar events in one view, with multi-calendar selection
- **Smart organization**: Today, Tomorrow, and This Week sections with overdue detection
- **Priority indicators**: P1-P4 badges with progressive prominence; non-primary calendars show a source badge
- **Interactive**: one-click copy, locations link to Google Maps, collapsible sections, weather badges
- **Proactive AI analysis**: the schedule is analyzed automatically; refresh for latest data, reset for a fresh analysis

<p align="center">
  <img src="web/tests/visual/planner.visual.ts-snapshots/dashboard-full-chromium-darwin.png" alt="Planner dashboard" width="720">
  <br><em>Todoist tasks and Calendar events in one schedule, analyzed proactively by the AI</em>
</p>

### Memory & Personalization
- **Long-term memory**: the assistant records facts about you and applies them across conversations. Writes happen through a tool that reports its result, so a rejected or failed write is visible rather than silently dropped
- **You stay in control**: inspect every memory on the Data page, delete any of them, or mark one **protected** so neither the model nor the nightly cleanup can remove it. Deletes are recoverable for a retention window
- **Provenance**: each memory records the conversation it was learned in
- **Nightly defragmentation**: an LLM pass merges duplicates and drops stale entries, with guards that refuse a plan which would grow the memory bank
- **Anonymous mode**: a per-conversation toggle that disables memory, conversation recall, and integrations. Persisted, so it survives a reload
- **Custom instructions**: free-text behavior tuning (e.g. "respond in Czech", "be concise")
- **User context**: location-aware units, currency, and recommendations

<p align="center">
  <img src="web/tests/visual/kv-store.visual.ts-snapshots/storage-page-memories-only-chromium-darwin.png" alt="Memories on the Data page" width="620">
  <br><em>Everything the assistant remembers about you is inspectable, deletable, and can be protected from automatic cleanup</em>
</p>

### Sports Tracking
- **Training programs**: running, cycling, pushups, anything - each with its own AI trainer conversation
- **Persistent coaching**: goals, preferences, routine, and progress persist per program
- **Garmin integration**: optional fitness data gives the trainer real context
- **Full control**: reset a program's conversation or delete the program entirely

<p align="center">
  <img src="web/tests/visual/planner.visual.ts-snapshots/health-summary-full-chromium-darwin.png" alt="Garmin health summary" width="760">
  <br><em>Garmin Connect data surfaces in the planner and gives the training coach real context</em>
</p>

### Language Learning
- **Language programs**: any language, each with a dedicated tutor conversation
- **AI-driven assessment**: an initial assessment sets the level, and lessons adapt
- **Interactive quizzes**: multiple-choice, fill-in-the-blank, translation, and batch quizzes rendered inline; all grading is done by the model
- **Progress tracking**: vocabulary, grammar, weak points, and session history persist

<p align="center">
  <img src="web/tests/visual/language.visual.ts-snapshots/quiz-batch-chromium-darwin.png" alt="Language learning quiz" width="320">
  <br><em>Interactive quizzes rendered inline - all grading is done by the model</em>
</p>

### Conversation Management
- **Full-text search** across all conversations and messages, with highlighted results
- **Pinned conversations** and optional one-line message previews in the sidebar
- **Deep linking**: bookmarkable URLs (`#/conversations/{id}`), including archived conversations
- **Real-time sync**: multi-device and multi-tab, with unread badges
- **Infinite scroll**: cursor-based pagination for conversations and messages
- **Archive**, rename, delete (an action sheet on mobile, with a configurable swipe quick action), and one-click copy of any message

<p align="center">
  <img src="web/tests/visual/search.visual.ts-snapshots/search-results-list-chromium-darwin.png" alt="Full-text search results" width="320">
  <br><em>Full-text search across every conversation</em>
</p>

### UI & Experience
- **Light, Dark, and System** color schemes with instant switching
- **Push notifications**: Web Push for agent results and reminders (iOS requires the app on the Home Screen)
- **Voice input**: speech-to-text via the Web Speech API, with language selection
- **Touch gestures**: swipe a conversation row for quick actions, swipe from the left edge for the sidebar, with haptic feedback where the platform allows it
- **Reliable sending**: an outbox keeps unsent messages through reloads and retries them - a tunnel or dead spot never eats a message
- **Offline app shell**: the service worker serves the app instantly and keeps it usable enough to read while offline
- **Cost tracking**: per-conversation and per-month API cost with currency conversion
- **Version banner**: new deployments are detected and offer a reload
- **Resilient**: toast notifications, retry on network errors, drafts persist per conversation, up-arrow recalls your last message
- Mobile-first responsive design, iOS Safari and PWA compatible

<p align="center">
  <img src="web/tests/visual/mobile.visual.ts-snapshots/mobile-conversation-chromium-darwin.png" alt="Mobile layout" width="300">
  <br><em>Installable as a PWA, with touch gestures, an offline shell, and push notifications</em>
</p>

### Authentication & Security
- Google Sign In with an email allowlist; local development runs without auth
- **Rate limiting** per user and per IP
- **Encryption at rest** for OAuth and Garmin tokens
- **Untrusted content handling**: web and browser output is fenced as data, never instructions, and high-impact actions triggered only by fetched content require confirmation
- **SSRF protection**: fetched URLs are validated against localhost and private ranges, including after DNS resolution

## Tech Stack

- **Backend**: Python 3.14, Flask (APIFlask/OpenAPI), LangGraph + LangChain, gunicorn
- **Frontend**: TypeScript (strict), Vite, Zustand - no UI framework
- **Database**: SQLite with yoyo migrations, FTS5 full-text search, WAL mode
- **LLM**: Google Gemini via `langchain-google-genai`, with context caching
- **Auth**: Google Identity Services + JWT
- **Tests**: pytest, Vitest, Playwright (E2E + visual regression)
- **Types**: OpenAPI spec exported from the backend generates the frontend's API types

## Quick Start

### Prerequisites

- Python 3.14+
- Node.js 18+ and npm
- Git LFS (for visual test screenshots)
- Google Gemini API key ([Get one here](https://aistudio.google.com/apikey))
- (Optional) Google Cloud project for authentication

### Installation

```bash
# Clone the repository
git clone https://github.com/jbrunclik/moneypenny.git
cd moneypenny

# Setup virtual environment and install dependencies
make setup

# Copy environment template
cp .env.example .env
```

### Configuration

[`.env.example`](.env.example) is the authoritative, commented list of every setting -
copy it and edit. Only one variable is strictly required:

```bash
GEMINI_API_KEY=your-gemini-api-key
```

For local development that is enough; `FLASK_ENV=development` skips authentication.
A production deployment additionally wants:

```bash
FLASK_ENV=production
GOOGLE_CLIENT_ID=your-client-id
JWT_SECRET_KEY=your-secret-key
ALLOWED_EMAILS=user1@gmail.com,user2@gmail.com
TOKEN_ENCRYPTION_KEY=            # generate with: make token-key (encrypts stored OAuth tokens)
```

Everything else is optional and has a sensible default. Grouped by area, with the
knobs worth knowing about:

| Area | Variables |
|---|---|
| Uploads | `MAX_FILE_SIZE`, `MAX_FILES_PER_MESSAGE`, `ALLOWED_FILE_TYPES` |
| Code sandbox | `CODE_SANDBOX_ENABLED`, `CODE_SANDBOX_IMAGE`, `CODE_SANDBOX_TIMEOUT`, `CODE_SANDBOX_MEMORY_LIMIT`, `CODE_SANDBOX_CPU_LIMIT` |
| Browser tool | `BROWSER_ENABLED`, `BROWSER_SESSION_TTL_SECONDS`, `BROWSER_MAX_CONCURRENT_SESSIONS`, `BROWSER_PAGE_TIMEOUT_MS` |
| Long-term memory | `MEMORY_MAX_ENTRIES`, `MEMORY_MAX_ENTRY_CHARS`, `MEMORY_WARNING_THRESHOLD`, `MEMORY_MAX_OPS_PER_CALL`, `MEMORY_SOFT_DELETE_RETENTION_DAYS`, `MEMORY_DEFRAG_THRESHOLD`, `MEMORY_DEFRAG_MODEL` |
| Context caching | `CONTEXT_CACHE_ENABLED`, `CONTEXT_CACHE_TTL_SECONDS`, `CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS` |
| Rate limiting | `RATE_LIMITING_ENABLED`, `RATE_LIMIT_STORAGE_URI`, `RATE_LIMIT_DEFAULT`, `RATE_LIMIT_AUTH`, `RATE_LIMIT_CHAT`, `RATE_LIMIT_CONVERSATIONS`, `RATE_LIMIT_FILES` |
| Server | `GUNICORN_WORKERS`, `GUNICORN_TIMEOUT`, `SSE_KEEPALIVE_INTERVAL` |
| Localization | `USER_LOCATION`, `COST_CURRENCY` |
| Push notifications | `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_CLAIMS_EMAIL` (generate with `make push-keys`) |
| Integrations | `TODOIST_*`, `GOOGLE_CALENDAR_*`, `GARMIN_API_TIMEOUT`, `WHATSAPP_*`, `WEATHER_LOCATION` |

### Optional Capabilities & Integrations

Every integration is optional and independently switched - leave its variables
empty and it simply doesn't appear. Step-by-step guides for all of them live in
**[docs/setup.md](docs/setup.md)**:

- **Code execution** - sandboxed Python in Docker (`make sandbox-image`)
- **Browser automation** - headless Chromium via Playwright (`make browser-setup`)
- **Google Sign In** - required for production authentication
- **Todoist**, **Google Calendar**, **Garmin Connect** - per-user OAuth / login connections
- **WhatsApp** - outbound notifications from autonomous agents (Meta Cloud API)

### Running

```bash
# Development (runs Flask + Vite dev servers concurrently)
make dev

# Visit http://localhost:5173 (Vite dev server with HMR)

# Production build
make build

# Run production server
make run

# Visit http://localhost:8000
```

## Commands

`make` with no arguments lists every target. The ones used day to day:

```bash
# Setup & running
make setup            # Create venv and install dependencies (Python + Node)
make dev              # Flask + Vite dev servers concurrently, with HMR
make build            # Production frontend build
make run              # Flask server (production mode)
make sandbox-image    # Build the Docker image for code execution
make browser-setup    # Install Playwright + Chromium for the browser tool

# Quality
make lint             # ruff + mypy + ESLint + tsc
make lint-fix         # Auto-fix what can be auto-fixed
make test             # Backend tests
make test-all         # Backend + frontend
make pre-commit       # lint + test-all + security scan
make audit            # Dependency vulnerability scan

# Visual regression
make test-fe-visual         # Run visual tests
make test-fe-visual-update  # Re-baseline after intentional UI changes
make test-fe-visual-report  # Open the HTML report to spot-check diffs

# Schema & types
make migration NAME=xxx   # Create a new database migration
make openapi              # Export the OpenAPI spec
make types                # Regenerate frontend API types from the spec

# Secrets
make token-key        # Generate the token-encryption key
make push-keys        # Generate VAPID keys for Web Push

# Operations
make deploy           # Deploy systemd service (full restart)
make reload           # Graceful reload, zero downtime (backend only)
make update           # Pull latest main + deps + rebuild frontend + graceful reload
make vacuum           # Reclaim database space
make backup           # Create a database backup
make backup-list      # List existing backups
make update-currency  # Refresh currency exchange rates
make defrag-memories  # Consolidate user memories (add -- --dry-run to preview)
```

## Testing

The project includes comprehensive test suites for both backend and frontend:

```bash
make test           # Run all backend tests
make test-unit      # Run unit tests only
make test-integration  # Run integration tests only
make test-cov       # Run with coverage report
make test-all       # Run all tests (backend + frontend)
```

### Backend Tests (pytest)

Tests are organized in `tests/`:
- `tests/unit/` - Unit tests for individual functions (costs, auth, tools, images)
- `tests/integration/` - Integration tests for API routes and database operations
- `tests/conftest.py` - Shared fixtures (isolated SQLite per test, mocked external services)

### Frontend Tests (Vitest + Playwright)

```bash
cd web
npm test            # Run Vitest unit/component tests
npm run test:e2e    # Run Playwright E2E tests
npm run test:all    # Run all frontend tests
```

Frontend tests are organized in `web/tests/`:
- `web/tests/unit/` - Unit tests for API client, DOM utilities, Zustand store
- `web/tests/component/` - Component tests with jsdom
- `web/tests/e2e/` - End-to-end browser tests
- `web/tests/visual/` - Visual regression tests

E2E tests run against a mock Flask server (`tests/e2e-server.py`) that simulates LLM responses without external API calls.

All external services (Gemini API, Google Auth, DuckDuckGo) are mocked - tests run offline and fast.

### Visual Regression

Baselines live next to their specs in `*-snapshots/` directories, stored in **Git LFS**,
with a set per platform: `*-darwin.png` for local runs and `*-linux.png` for CI (font
rendering differs per platform). Things to know before touching them:

- The mock server serves the **built** frontend, so a CSS or markup change needs `make build`
  before `make test-fe-visual` will see it.
- After an intentional UI change, re-baseline locally with `make test-fe-visual-update` and
  review the diffs (`make test-fe-visual-report`) rather than trusting a green run.
- Linux baselines are regenerated by the **Update Visual Baselines** workflow (manual
  dispatch) - download its artifact and commit the refreshed PNGs.

## Deployment

For production, the app uses Gunicorn as the WSGI server. A systemd user service file is included for Linux:

```bash
# Set production environment in .env
FLASK_ENV=production

# Install dependencies (includes gunicorn)
make setup

# Deploy and start the service
make deploy

# Enable lingering (keeps service running after logout)
sudo loginctl enable-linger $USER

# View logs
journalctl --user -u moneypenny -f
```

The systemd service automatically runs `npm install && npm run build` before starting Gunicorn.

**Important**: User services are tied to login sessions by default. The `enable-linger` command ensures your service continues running after you disconnect from SSH.

### Zero-Downtime Updates

After the initial deployment, use graceful reloads for zero-downtime updates:

```bash
# Pull latest changes
git pull

# Option 1: Backend-only changes (Python code) - fastest
make reload

# Option 2: Any changes (backend + frontend + dependencies)
make update
```

**How it works**: The `reload` command sends `SIGHUP` to gunicorn, which spawns new workers and gracefully shuts down old ones after they finish current requests. No connections are dropped.

| Command | Use When | Downtime |
|---------|----------|----------|
| `make reload` | Python code changes only | None |
| `make update` | Frontend, dependencies, or full update | None |
| `make deploy` | First deployment or systemd config changes | Brief (~5s) |

### Scheduled Jobs, nginx, and Logs

Production maintenance runs on systemd timers: daily database **backups**,
weekly **VACUUM**, daily **currency rate** updates, and a nightly LLM-driven
**memory defragmentation** pass. Reverse-proxy (nginx) configuration for SSE
streaming and journald log management are documented alongside them in
**[docs/deployment.md](docs/deployment.md)**.


## Project Structure

```
moneypenny/
├── src/                          # Flask backend
│   ├── app.py                    # Entry point, Vite manifest loading, /privacy, /sw.js
│   ├── config.py                 # All environment configuration and model definitions
│   ├── api/
│   │   ├── routes/               # 18 modules of REST endpoints, split by feature
│   │   ├── helpers/              # Streaming, save pipeline, stream resume
│   │   ├── schemas.py            # Pydantic request/response schemas (source of the OpenAPI spec)
│   │   └── rate_limiting.py
│   ├── agent/                    # LangGraph agent
│   │   ├── graph.py              # Nodes, routing, self-correction
│   │   ├── prompts.py            # System prompts (static/cacheable vs per-request)
│   │   ├── tools/                # One module per tool
│   │   ├── executor.py           # Autonomous agent execution
│   │   ├── permissions.py        # Agent tool permission gates
│   │   ├── context_cache.py      # Gemini context caching
│   │   └── compaction.py         # Long-conversation summarization
│   ├── auth/                     # Google Sign In, JWT, OAuth for integrations
│   ├── db/                       # SQLite models, connection pool, blob store
│   ├── templates/                # Jinja2 shell + privacy policy
│   └── utils/                    # Images, costs, logging, push, weather, files
├── web/                          # Vite + TypeScript frontend
│   └── src/
│       ├── core/                 # Conversation, messaging, programs, toolbar, kv-store
│       ├── components/           # UI modules (messages/, dashboards, popups)
│       ├── state/store.ts        # Zustand store
│       ├── api/client.ts         # Typed fetch wrapper
│       ├── types/                # Hand-written + OpenAPI-generated types
│       ├── sync/                 # Multi-device sync manager
│       ├── gestures/             # Touch handlers
│       └── styles/               # Modular CSS
├── migrations/                   # yoyo migrations (schema history)
├── tests/                        # Backend: unit/ and integration/, plus the E2E mock server
├── web/tests/                    # Frontend: unit, component, e2e/, visual/ (LFS baselines)
├── scripts/                      # Operational scripts (backup, vacuum, defrag, cost analysis)
├── systemd/                      # Service + timer units for the app and scheduled jobs
├── docs/                         # Architecture and per-feature documentation
├── static/                       # Build output, PWA manifest, OpenAPI spec
└── Makefile                      # Everything runnable
```

## Documentation

Detailed docs live in [`docs/`](docs/README.md):

| Topic | |
|---|---|
| Agents & tools | [features/agents.md](docs/features/agents.md) |
| Memory & context | [features/memory-and-context.md](docs/features/memory-and-context.md) |
| Chat & streaming | [features/chat-and-streaming.md](docs/features/chat-and-streaming.md) |
| Integrations | [features/integrations.md](docs/features/integrations.md) |
| Language learning | [features/language-learning.md](docs/features/language-learning.md) |
| Search | [features/search.md](docs/features/search.md) |
| Sync | [features/sync.md](docs/features/sync.md) |
| Push notifications | [features/push-notifications.md](docs/features/push-notifications.md) |
| Cost tracking | [features/cost-tracking.md](docs/features/cost-tracking.md) |
| API design | [architecture/api-design.md](docs/architecture/api-design.md) |
| Database | [architecture/database.md](docs/architecture/database.md) |
| Authentication | [architecture/authentication.md](docs/architecture/authentication.md) |
| Setup guides (integrations) | [setup.md](docs/setup.md) |
| Production operations | [deployment.md](docs/deployment.md) |
| Testing | [testing.md](docs/testing.md) |
| Code conventions | [conventions.md](docs/conventions.md) |

## License

MIT
