# AI Chatbot

A personal, self-hosted AI assistant built on Google Gemini. Chat is the entry point,
but it also runs a planner over your tasks and calendar, coaches training programs,
teaches languages, and executes autonomous agents on a schedule.

Built for a household of a few users, deployed on a single box.

**[Features](#features)** · **[Screenshots](#screenshots)** · **[Quick Start](#quick-start)** ·
**[Documentation](docs/README.md)** · **[Commands](#commands)**

---

## Screenshots

<p align="center">
  <img src="web/tests/visual/chat.visual.ts-snapshots/conversation-with-messages-chromium-darwin.png" alt="Desktop chat interface" width="820">
  <br><em>Chat with streaming responses, markdown rendering, syntax highlighting, and an expandable trace of the model's thinking and tool calls</em>
</p>

<table align="center">
  <tr>
    <td align="center" width="50%">
      <img src="web/tests/visual/planner.visual.ts-snapshots/dashboard-full-chromium-darwin.png" alt="Planner dashboard" width="400">
      <br><strong>Planner</strong>
      <br><em>Todoist tasks and Calendar events in one schedule, analyzed proactively by the AI</em>
    </td>
    <td align="center" width="50%">
      <img src="web/tests/visual/agents.visual.ts-snapshots/command-center-with-approvals-chromium-darwin.png" alt="Agent command center with pending approvals" width="400">
      <br><strong>Autonomous agents</strong>
      <br><em>Destructive actions wait for approval, showing the exact tool and arguments</em>
    </td>
  </tr>
</table>

<p align="center">
  <img src="web/tests/visual/kv-store.visual.ts-snapshots/storage-page-memories-only-chromium-darwin.png" alt="Memories on the Data page" width="560">
  <br><strong>Memory, fully inspectable</strong>
  <br><em>Everything the assistant remembers about you, with per-entry protection against automatic deletion</em>
</p>

<table align="center">
  <tr>
    <td align="center">
      <img src="web/tests/visual/language.visual.ts-snapshots/quiz-batch-chromium-darwin.png" alt="Language learning quiz" width="230">
      <br><strong>Language quizzes</strong>
      <br><em>Interactive, graded by the model</em>
    </td>
    <td align="center">
      <img src="web/tests/visual/search.visual.ts-snapshots/search-results-list-chromium-darwin.png" alt="Full-text search results" width="230">
      <br><strong>Full-text search</strong>
      <br><em>Across every conversation</em>
    </td>
    <td align="center">
      <img src="web/tests/visual/mobile.visual.ts-snapshots/mobile-conversation-chromium-darwin.png" alt="Mobile layout" width="195">
      <br><strong>Mobile / PWA</strong>
      <br><em>Installable, touch gestures</em>
    </td>
  </tr>
</table>

<p align="center">
  <img src="web/tests/visual/planner.visual.ts-snapshots/health-summary-full-chromium-darwin.png" alt="Garmin health summary" width="760">
  <br><em>Garmin Connect data surfaces in the planner and gives the training coach real context</em>
</p>

<p align="center"><sub>All screenshots are visual regression baselines from the test suite, so they cannot drift from the real UI.</sub></p>

## Features

### Chat & AI
- Two models: **Gemini 3.6 Flash** ("Fast", the default) and **Gemini 3.1 Pro** ("Advanced") - switchable per conversation
- **Streaming responses**: token-by-token display (toggleable) with a thinking indicator that shows model reasoning and live tool activity
- **Resumable streams**: a dropped connection reconnects and replays the response from a server-side journal instead of losing it
- **Stop streaming**: abort mid-generation
- **Agentic planning**: complex multi-tool requests get an execution plan before the first tool call
- **Self-correcting tools**: on a tool failure the model reads the error and retries differently, up to a configurable limit
- **Long-chat compaction**: older turns are summarized non-destructively so long conversations stay affordable without losing history
- **Prompt caching**: the static system prompt and tool definitions live in Gemini's context cache
- Markdown rendering with syntax highlighting

### Tools & Capabilities
- **File uploads**: images, PDFs, and text files with multimodal analysis; paste screenshots straight from the clipboard
- **Image generation**: create images from text, or edit an uploaded one; click any thumbnail for a full-size lightbox
- **Web tools**: web search (DuckDuckGo), URL fetching with source citations, and full browser automation - JS rendering, clicks, form filling, screenshots (Playwright)
- **Code execution**: Python in a sandboxed Docker container for calculations, data analysis, charts, and PDFs
- **Conversation recall**: the assistant can search and read your past conversations, so "what did we decide about X?" does not depend on it having memorized X
- **Todoist**: list, add, complete, prioritize, and organize tasks across projects
- **Google Calendar**: schedule meetings and focus blocks, update events, RSVP
- **Garmin Connect**: steps, sleep, heart rate, HRV, SpO2, training readiness, activities
- **WhatsApp**: outbound notifications from autonomous agents
- **Key-value storage**: durable structured state for agents and program conversations

### Memory & Personalization
- **Long-term memory**: the assistant records facts about you and applies them across conversations. Writes happen through a tool that reports its result, so a rejected or failed write is visible rather than silently dropped
- **You stay in control**: inspect every memory on the Data page, delete any of them, or mark one **protected** so neither the model nor the nightly cleanup can remove it. Deletes are recoverable for a retention window
- **Provenance**: each memory records the conversation it was learned in
- **Nightly defragmentation**: an LLM pass merges duplicates and drops stale entries, with guards that refuse a plan which would grow the memory bank
- **Anonymous mode**: a per-conversation toggle that disables memory, conversation recall, and integrations. Persisted, so it survives a reload
- **Custom instructions**: free-text behavior tuning (e.g. "respond in Czech", "be concise")
- **User context**: location-aware units, currency, and recommendations

### Planner Dashboard
- **Unified schedule**: Todoist tasks and Calendar events in one view, with multi-calendar selection
- **Smart organization**: Today, Tomorrow, and This Week sections with overdue detection
- **Priority indicators**: P1-P4 badges with progressive prominence; non-primary calendars show a source badge
- **Interactive**: one-click copy, locations link to Google Maps, collapsible sections, weather badges
- **Proactive AI analysis**: the schedule is analyzed automatically; refresh for latest data, reset for a fresh analysis

### Sports Tracking
- **Training programs**: running, cycling, pushups, anything - each with its own AI trainer conversation
- **Persistent coaching**: goals, preferences, routine, and progress persist per program
- **Garmin integration**: optional fitness data gives the trainer real context
- **Full control**: reset a program's conversation or delete the program entirely

### Language Learning
- **Language programs**: any language, each with a dedicated tutor conversation
- **AI-driven assessment**: an initial assessment sets the level, and lessons adapt
- **Interactive quizzes**: multiple-choice, fill-in-the-blank, translation, and batch quizzes rendered inline; all grading is done by the model
- **Progress tracking**: vocabulary, grammar, weak points, and session history persist

### Autonomous Agents
- **Scheduled execution**: cron-scheduled agents that run unattended
- **Command Center**: every agent, pending approval, and recent run in one dashboard
- **Approval workflow**: destructive actions are blocked in code until you approve them - not merely discouraged in the prompt
- **Tool permissions**: per-agent allowlists. Capabilities that outlive the run, such as writing to long-term memory, must be granted explicitly
- **Agent-to-agent**: agents can trigger other agents for multi-step workflows
- **Dedicated conversations**: each agent has its own conversation and history

### Conversation Management
- **Full-text search** across all conversations and messages, with highlighted results
- **Deep linking**: bookmarkable URLs (`#/conversations/{id}`)
- **Real-time sync**: multi-device and multi-tab, with unread badges
- **Infinite scroll**: cursor-based pagination for conversations and messages
- **Archive**, rename, delete, and one-click copy of any message

### UI & Experience
- **Light, Dark, and System** color schemes with instant switching
- **Push notifications**: Web Push for agent results and reminders (iOS requires the app on the Home Screen)
- **Voice input**: speech-to-text via the Web Speech API, with language selection
- **Touch gestures**: swipe a conversation to rename or delete, swipe from the left edge for the sidebar
- **Cost tracking**: per-conversation and per-month API cost with currency conversion
- **Version banner**: new deployments are detected and offer a reload
- **Resilient**: toast notifications, retry on network errors, draft preservation
- Mobile-first responsive design, iOS Safari and PWA compatible

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
git clone https://github.com/jbrunclik/ai-chatbot.git
cd ai-chatbot

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

The integration setup guides below cover the OAuth apps those variables point at.

### Setting up Code Execution (Docker)

The code execution feature allows the AI to run Python code in a secure, isolated Docker container. This is optional but enables powerful capabilities like data analysis, chart generation, and PDF creation.

**Prerequisites:**
- Docker installed and running
- User must have access to the Docker socket

**Build the custom sandbox image:**

```bash
make sandbox-image
```

This creates `ai-chatbot-sandbox:local` with pre-installed fonts and Python libraries for faster execution.

**Local Development (macOS/Linux):**
```bash
# Docker Desktop on macOS/Windows handles permissions automatically
# On Linux, add your user to the docker group:
sudo usermod -aG docker $USER
# Log out and back in for group changes to take effect
```

**Production Server (Linux with systemd):**

If running the app as a systemd service, the service user needs Docker socket access:

```bash
# 1. Add the service user to the docker group
sudo usermod -aG docker $USER

# 2. If using socket activation, ensure the socket is accessible
# Check socket permissions:
ls -la /var/run/docker.sock
# Should show: srw-rw---- 1 root docker ...

# 3. If still having issues, you may need to restart the Docker service:
sudo systemctl restart docker

# 4. Restart your application service:
systemctl --user restart ai-chatbot
```

**Disabling Code Execution:**

If you don't want to set up Docker, simply disable the feature:
```bash
CODE_SANDBOX_ENABLED=false
```

The AI will gracefully handle this and won't offer code execution capabilities.

**Security Notes:**
- Code runs in isolated containers with no network access
- Containers have memory and CPU limits
- Files are only accessible within the sandbox (`/output/` directory)
- Each execution creates a fresh container that is destroyed after use

### Setting up Browser Automation

The browser tool gives the AI a full headless Chromium browser. Unlike simple URL fetching, it renders JavaScript, maintains session state (cookies, history) across turns, and can click buttons, fill forms, and take screenshots. Useful for SPAs, paywalled previews, and any page that requires interaction.

**Prerequisites:**
- Python `playwright` package and Chromium browser binary

**Install:**

```bash
make browser-setup
```

This runs `pip install playwright` and `playwright install chromium --with-deps` inside the virtual environment.

**Configuration (`.env`):**
```bash
BROWSER_ENABLED=true                 # Enable/disable (default: true)
BROWSER_SESSION_TTL_SECONDS=600      # Idle session cleanup (default: 600 s)
BROWSER_MAX_CONCURRENT_SESSIONS=5    # Max simultaneous sessions (default: 5)
BROWSER_PAGE_TIMEOUT_MS=30000        # Per-action timeout (default: 30 000 ms)
```

**Disabling:**

Set `BROWSER_ENABLED=false` to disable the tool. The AI will fall back to `fetch_url` for web content. If Playwright is not installed, the tool returns a graceful error rather than crashing.

**Security:**
- All URLs are validated against an SSRF blocklist (private IP ranges, loopback, link-local) before navigation
- The browser never stores or enters passwords

### Setting up Todoist Integration

The Todoist integration allows the AI to manage your tasks - list, add, complete, prioritize, and organize tasks across projects. Each user connects their own Todoist account via OAuth.

**Prerequisites:**
- A Todoist account
- A registered Todoist OAuth app

**Setup:**

1. Go to [Todoist App Console](https://developer.todoist.com/appconsole.html)
2. Click **Create a new app**
3. Fill in the app details:
   - **App name**: Your chatbot name
   - **App service URL**: Your deployment URL (e.g., `https://yourdomain.com`)
   - **OAuth redirect URL**: Your deployment URL (e.g., `https://yourdomain.com` for production, `http://localhost:5173` for development with Vite)
4. Copy the **Client ID** and **Client Secret** to your `.env` file

**Configuration:**
```bash
TODOIST_CLIENT_ID=your-client-id
TODOIST_CLIENT_SECRET=your-client-secret
TODOIST_REDIRECT_URI=http://localhost:5173  # Your app URL (use Vite port in dev)
```

**Usage:**
1. Open Settings (gear icon in sidebar)
2. Click "Connect Todoist" in the Todoist Integration section
3. Authorize the app on Todoist's OAuth page
4. Once connected, ask the AI to help manage your tasks:
   - "Show me my tasks for today"
   - "What's overdue?"
   - "Add a task to buy groceries"
   - "Mark the first task as complete"
   - "Prioritize my work project tasks"

**Disabling Todoist:**

Simply leave `TODOIST_CLIENT_ID` empty - the integration won't appear in settings and the AI won't offer task management capabilities.

### Setting up Google Sign In

To enable authentication (required for production):

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a new project (or select an existing one)
3. Configure the **OAuth consent screen**:
   - Go to **APIs & Services** → **OAuth consent screen**
   - Select **External** (or Internal for Google Workspace)
   - Fill in required fields (app name, support email)
   - Add your email(s) as test users (required while in "Testing" status)
   - To move from "Testing" to "Production", add your app's `/privacy` URL as the privacy policy link — the app serves this page at `https://yourdomain.com/privacy`
4. Create **OAuth credentials**:
   - Click **Create Credentials** → **OAuth client ID**
   - Select **Web application** as the application type
   - Add **Authorized JavaScript origins**:
     - `http://localhost:5173` (for development with Vite)
     - `https://yourdomain.com` (for production)
   - Copy the **Client ID** to your `.env` file

No client secret is needed - the app uses Google Identity Services which validates tokens server-side.

### Setting up Google Calendar Integration

The Google Calendar integration allows the AI to schedule meetings, create focus blocks, update events, and RSVP to invitations. Each user connects their own Google Calendar account via OAuth.

**Cost:** Google Calendar API is **free** for personal use with generous quotas (1,000,000 queries/day).

**Setup:**

1. Use the same Google Cloud project as your Sign-In client (or create a new one)
2. Enable the **Google Calendar API**:
   - Go to **APIs & Services** → **Library**
   - Search for "Google Calendar API"
   - Click **Enable**
3. Create a **separate OAuth client** for Calendar:
   - Go to **APIs & Services** → **Credentials**
   - Click **Create Credentials** → **OAuth client ID**
   - Select **Web application**
   - Add **Authorized redirect URIs** (not JavaScript origins):
     - `http://localhost:5173` (for development with Vite)
     - `https://yourdomain.com` (for production)
   - Copy the **Client ID** and **Client Secret**

**Why a separate OAuth client?** The Sign-In client uses Google Identity Services (no secret needed), while Calendar uses standard OAuth with a secret. Separate clients let users use the chatbot without granting calendar access.

**Configuration:**
```bash
GOOGLE_CALENDAR_CLIENT_ID=your-calendar-client-id
GOOGLE_CALENDAR_CLIENT_SECRET=your-calendar-client-secret
GOOGLE_CALENDAR_REDIRECT_URI=http://localhost:5173  # Use Vite port in dev
```

**Usage:**
1. Open Settings (gear icon in sidebar)
2. Click "Connect Google Calendar"
3. Authorize on Google's OAuth page
4. Select which calendars to include in the planner (work, personal, shared calendars)
   - Primary calendar is always included
   - Events from multiple calendars are combined in the planner dashboard
   - Calendar labels help distinguish events from different calendars
5. Ask the AI to manage your calendar:
   - "What's on my calendar today?"
   - "Schedule a meeting with John tomorrow at 2pm"
   - "Block 2 hours for deep work on Monday morning"
   - "Cancel my 3pm meeting"

**Disabling:** Leave `GOOGLE_CALENDAR_CLIENT_ID` empty - the integration won't appear.

### Setting up Garmin Connect Integration

The Garmin Connect integration allows the AI to query your health and fitness data — steps, sleep, heart rate, HRV, SpO2, body composition, training readiness, and activities. It is read-only; no data is written to Garmin.

**Prerequisites:**
- A Garmin Connect account

**No app registration required** — users authenticate with their own Garmin email and password. The password is never stored; only session tokens (valid ~1 year) are persisted.

**MFA support:** If your Garmin account has two-factor authentication enabled, you will be prompted for a verification code after entering your credentials.

**Configuration:**
```bash
GARMIN_API_TIMEOUT=15  # Optional, default is 15 seconds
```

**Usage:**
1. Open Settings (gear icon in sidebar)
2. Click "Connect Garmin" and enter your Garmin Connect email and password
3. If MFA is enabled, enter the verification code from your email or authenticator app
4. Once connected, ask the AI about your fitness data:
   - "How did I sleep last night?"
   - "What's my training readiness today?"
   - "Show me my last 5 runs"
   - "What was my resting heart rate this week?"

**Disabling:** If you do not want Garmin Connect to appear, it is available whenever the `garminconnect` Python package is installed (included in `requirements.txt`). Users who do not connect their account simply won't have the tool available.

### Setting up WhatsApp Integration (Autonomous Agents)

The WhatsApp integration allows autonomous agents to send execution results and notifications to your phone via WhatsApp. This uses Meta's official WhatsApp Cloud API.

**Cost:** WhatsApp Cloud API offers **1,000 free conversations/month**. Beyond that, costs are ~$0.005-0.05 per conversation depending on region.

**Prerequisites:**
- A Meta (Facebook) account
- A phone number to receive messages (can be your personal WhatsApp number)

**Key Concepts:**

Before setting up, understand these important WhatsApp Business API concepts:

- **Phone Number ID**: A numeric ID (e.g., `982966681562240`), NOT the phone number itself. This is a common mistake!
- **Phone Registration**: Your business phone must be registered via the API before it can send messages
- **24-Hour Window**: You can only send free-form text messages within 24 hours after a user messages you first
- **Template Messages**: For business-initiated conversations (first contact), you MUST use pre-approved message templates
- **Test vs Production**: The `hello_world` template only works with test phone numbers, not production

**Setup:**

1. **Create a Meta Business Account** (if you don't have one):
   - Go to [Meta Business Suite](https://business.facebook.com/)
   - Click "Create Account" and follow the prompts

2. **Create a WhatsApp Business App**:
   - Go to [Meta for Developers](https://developers.facebook.com/)
   - Click "My Apps" → "Create App"
   - Select "Business" as the app type
   - Fill in app details and click "Create App"

3. **Add WhatsApp to your app**:
   - In your app dashboard, click "Add Product"
   - Find "WhatsApp" and click "Set Up"

4. **Add your business phone number**:
   - Go to **WhatsApp** → **API Setup**
   - Click "Add phone number" and follow the verification process
   - You may need to download a certificate to verify ownership
   - Once verified, note the **Phone number ID** (a numeric ID like `982966681562240`)

5. **Register your phone number** (required before sending):
   ```bash
   curl -X POST "https://graph.facebook.com/v18.0/YOUR_PHONE_NUMBER_ID/register" \
     -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"messaging_product": "whatsapp", "pin": "123456"}'
   ```
   You should see `{"success": true}`.

6. **Generate a permanent access token**:
   - Go to **Business Settings** → **System Users**
   - Create a System User with "Admin" role
   - Click "Generate Token" → Select your WhatsApp app
   - Add permissions: `whatsapp_business_messaging`, `whatsapp_business_management`
   - Copy the permanent token to your `.env` file

7. **Create a message template** (required for business-initiated messages):
   - Go to [Meta Business Suite](https://business.facebook.com/) → **WhatsApp Manager** → **Message Templates**
   - Create a new template (e.g., name: `agent_notification`, category: `UTILITY`)
   - Use a body with two variables: `{{1}}: {{2}}`
     - `{{1}}` = Agent name (e.g., "Daily Briefing Agent")
     - `{{2}}` = Message content
   - Submit for review (usually approved within minutes for utility templates)
   - Note the template name for your `.env` file

8. **Enable billing** (for production):
   - Go to **WhatsApp** → **API Setup** → **Payment settings**
   - Add a payment method to enable production messaging
   - Without billing, you can only message numbers added to your test recipient list

**Configuration:**
```bash
# WhatsApp Cloud API credentials (app-level)
# IMPORTANT: Phone Number ID is a numeric ID, NOT the phone number!
WHATSAPP_PHONE_NUMBER_ID=982966681562240          # From API Setup page (numeric ID)
WHATSAPP_ACCESS_TOKEN=EAAxxxxxxx...               # Permanent token from System User
WHATSAPP_TEMPLATE_NAME=agent_notification         # Your approved template name
```

**User Setup:**

Each user needs to configure their WhatsApp phone number in the app settings (Settings → WhatsApp). The phone number must be:
- In E.164 format (e.g., `+1234567890`)
- A valid WhatsApp account

**Usage:**

WhatsApp messaging is available as an agent tool. To enable it for an autonomous agent:

1. Add `whatsapp` to the agent's tool permissions
2. Include instructions in the agent's system prompt to send WhatsApp notifications, e.g.:
   - "After completing your analysis, send the results via WhatsApp"
   - "Notify me via WhatsApp when the task is done"

The agent will only send WhatsApp messages when explicitly instructed in its goals.

**Testing the setup:**

For testing within the 24-hour window (after user messages you):
```bash
curl -X POST "https://graph.facebook.com/v18.0/$WHATSAPP_PHONE_NUMBER_ID/messages" \
  -H "Authorization: Bearer $WHATSAPP_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "messaging_product": "whatsapp",
    "to": "1234567890",
    "type": "text",
    "text": {"body": "Hello from AI Chatbot!"}
  }'
```

For business-initiated messages (using template with two parameters):
```bash
curl -X POST "https://graph.facebook.com/v18.0/$WHATSAPP_PHONE_NUMBER_ID/messages" \
  -H "Authorization: Bearer $WHATSAPP_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "messaging_product": "whatsapp",
    "to": "1234567890",
    "type": "template",
    "template": {
      "name": "agent_notification",
      "language": {"code": "en"},
      "components": [{"type": "body", "parameters": [{"type": "text", "text": "Test Agent"}, {"type": "text", "text": "Your task is complete!"}]}]
    }
  }'
```

**Troubleshooting:**

| Error | Cause | Solution |
|-------|-------|----------|
| `133010 Account not registered` | Business phone not registered | Run the `/register` endpoint (step 5) |
| `131030 Recipient not in allowed list` | Test mode limitation | Add recipient to test list or enable billing |
| `131058 Hello World templates can only be sent from Public Test Numbers` | Using hello_world in production | Create your own message template |
| `100 messaging_product is required` | Malformed request | Check JSON structure and Content-Type header |

**Limitations:**
- Template messages required for first contact (outside 24-hour window)
- Templates must be pre-approved by Meta (usually quick for utility category)
- Messages have a 4096 character limit (longer content is automatically truncated)
- Rate limits apply based on your messaging tier (starts at 250 messages/day)

**Disabling:** Leave `WHATSAPP_PHONE_NUMBER_ID` empty - the integration won't be available.

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

# Visual regression (baselines are darwin-only; CI skips them)
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

Baselines live next to their specs in `*-snapshots/` directories, stored in **Git LFS**, and
are **darwin-only** - CI skips visual tests because font rendering differs per platform. Two
things to know before touching them:

- The mock server serves the **built** frontend, so a CSS or markup change needs `make build`
  before `make test-fe-visual` will see it.
- After an intentional UI change, re-baseline with `make test-fe-visual-update` and review the
  diffs (`make test-fe-visual-report`) rather than trusting a green run.

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
journalctl --user -u ai-chatbot -f
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

### Database Vacuum

A weekly systemd timer is automatically configured to run VACUUM on both SQLite databases (main database and blob storage). This reclaims disk space from deleted records and optimizes database performance.

```bash
# Check timer status
systemctl --user list-timers

# View vacuum logs
journalctl --user -u ai-chatbot-vacuum

# Run vacuum manually
make vacuum
```

### Currency Rate Updates

A daily systemd timer updates currency exchange rates from a free API (no API key required). Rates are stored in the database and used for cost display without requiring an app restart.

```bash
# View currency update logs
journalctl --user -u ai-chatbot-currency

# Run update manually
make update-currency
```

### Database Backup

A daily systemd timer creates timestamped snapshots of both SQLite databases (main database and blob storage), keeping 7 days of history by default. Backups use SQLite's online backup API for consistent snapshots even while the database is in use.

```bash
# Check timer status
systemctl --user list-timers

# View backup logs
journalctl --user -u ai-chatbot-backup

# Create backup manually
make backup

# List existing backups
make backup-list
```

Backups are stored in `backups/{database_name}/` directories alongside the databases. Each backup file is named with a timestamp: `chatbot-20240101-120000.db`.

### Memory Defragmentation

A nightly systemd timer consolidates and cleans up user memories using an LLM: it merges
related memories, removes duplicates, drops stale entries, and purges soft-deleted memories
whose recovery window has passed.

The job is deliberately conservative. It asks the model for a schema-validated plan rather
than parsing prose, it refuses a plan that would leave the user with *more* memories than it
started with, it skips memories marked protected, and its deletes are soft - so a bad run is
recoverable until the retention window expires.

```bash
# View defrag logs
journalctl --user -u ai-chatbot-memory-defrag

# Run defragmentation manually
make defrag-memories

# Preview changes without applying (dry run)
make defrag-memories -- --dry-run
```

Only users with `MEMORY_DEFRAG_THRESHOLD` memories or more are processed (default: 30).

### Reverse Proxy (nginx)

If running behind nginx, ensure timeouts and compression are configured:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;

    # Standard proxy headers
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # Timeouts - must match or exceed GUNICORN_TIMEOUT
    proxy_connect_timeout 60s;
    proxy_send_timeout 300s;    # Match GUNICORN_TIMEOUT
    proxy_read_timeout 300s;    # Match GUNICORN_TIMEOUT

    # Disable buffering for streaming responses
    proxy_buffering off;

    # Gzip compression (add to http or server block)
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_proxied any;
    gzip_types text/plain text/css text/javascript application/javascript application/json application/xml text/xml;
    gzip_comp_level 6;
}
```

**Note on gzip**: The gzip directives can also be placed in the `http` or `server` block to apply globally. The `gzip_vary on` directive ensures proper caching behavior with CDNs. Compression is skipped for already-compressed formats (images, PDFs) and responses smaller than `gzip_min_length`.

The app uses SSE keepalive heartbeats (configurable via `SSE_KEEPALIVE_INTERVAL`) to prevent proxy timeouts during LLM "thinking" phases. For very long operations, increase both `GUNICORN_TIMEOUT` and nginx timeouts.

### Log Rotation and Disk Space

The systemd service file includes log rate limiting to prevent disk space issues, especially when using `LOG_LEVEL=DEBUG`. The default settings allow ~333 log messages per second.

**Service-level limits** (configured in `ai-chatbot.service`):
- `LogRateLimitIntervalSec=30`: Time window for rate limiting
- `LogRateLimitBurst=10000`: Maximum messages per interval

**Global journald limits** (optional, requires root):

To configure system-wide journald limits, create or edit `/etc/systemd/journald.conf.d/ai-chatbot.conf`:

```ini
[Journal]
# Maximum disk space for journal (default: 10% of filesystem)
SystemMaxUse=1G

# Maximum disk space for persistent journal
SystemKeepFree=500M

# Maximum age of journal entries (older entries are deleted)
MaxRetentionSec=7day

# Maximum number of journal files to keep
MaxFiles=10
```

After modifying journald configuration:
```bash
sudo systemctl restart systemd-journald
```

**Viewing log sizes:**
```bash
# Check journal disk usage
journalctl --user --disk-usage

# Check service-specific log size
journalctl --user -u ai-chatbot --disk-usage

# Clean old logs (keeps last 7 days)
journalctl --user --vacuum-time=7d
```

**Monitoring log volume:**
When running with `LOG_LEVEL=DEBUG`, monitor disk usage regularly:
```bash
# Watch journal size
watch -n 60 'journalctl --user --disk-usage'
```

## Project Structure

```
ai-chatbot/
├── src/                          # Flask backend
│   ├── app.py                    # Entry point, Vite manifest loading, /privacy, /sw.js
│   ├── config.py                 # All environment configuration and model definitions
│   ├── api/
│   │   ├── routes/               # 18 modules of REST endpoints, split by feature
│   │   ├── helpers/              # Streaming, save pipeline, stream resume
│   │   ├── schemas.py            # Pydantic request/response schemas (source of the OpenAPI spec)
│   │   └── rate_limiting.py
│   ├── agent/                    # LangGraph agent
│   │   ├── graph.py              # Nodes, routing, planning, self-correction
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
| Testing | [testing.md](docs/testing.md) |
| Code conventions | [conventions.md](docs/conventions.md) |

## License

MIT
