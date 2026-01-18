# AI Chatbot

A personal AI chatbot web application using Google Gemini APIs, similar to ChatGPT.

## Screenshots

### Desktop Interface

<p align="center">
  <img src="web/tests/visual/chat.visual.ts-snapshots/conversation-with-messages-chromium-darwin.png" alt="Desktop chat interface" width="700">
</p>
<p align="center"><em>Chat interface with message history, markdown rendering, and syntax highlighting</em></p>

### Sidebar & Mobile

<table align="center">
  <tr>
    <td align="center">
      <img src="web/tests/visual/chat.visual.ts-snapshots/sidebar-conversations-chromium-darwin.png" alt="Sidebar with conversations" width="280">
      <br><em>Conversation list with search</em>
    </td>
    <td align="center">
      <img src="web/tests/visual/mobile.visual.ts-snapshots/mobile-sidebar-open-chromium-darwin.png" alt="Mobile layout" width="200">
      <br><em>Mobile-responsive layout</em>
    </td>
  </tr>
</table>

### Planner Dashboard

<p align="center">
  <img src="web/tests/visual/planner.visual.ts-snapshots/dashboard-full-chromium-darwin.png" alt="Planner dashboard with tasks and events" width="700">
</p>
<p align="center"><em>Unified view of your schedule - combining Todoist tasks and Google Calendar events with priority indicators</em></p>

<p align="center"><sub>Screenshots from visual regression tests - always up-to-date with the latest UI.</sub></p>

## Features

### Chat & AI
- Chat with Google Gemini AI models (Pro and Flash)
- **Streaming responses**: Real-time token-by-token display (toggleable) with thinking indicator showing model processing and tool activity
- **Stop streaming**: Abort streaming responses mid-generation
- Model selection (Gemini 3 Pro for complex tasks, Flash for speed)
- Markdown rendering with syntax highlighting

### Tools & Capabilities
- **File uploads**: Images, PDFs, and text files with multimodal AI analysis
- **Clipboard paste**: Paste screenshots directly from clipboard (Cmd+V / Ctrl+V)
- **Image generation**: Generate images from text descriptions, or edit uploaded images
- **Image lightbox**: Click thumbnails to view full-size images, with loading indicator and on-demand thumbnail loading
- **Web tools**: Real-time web search (DuckDuckGo) and URL fetching with source citations
- **Code execution**: Secure Python sandbox for calculations, data analysis, and generating PDFs/charts
- **Todoist integration**: Manage tasks via AI - list, add, complete, prioritize, and organize tasks across projects
- **Google Calendar integration**: Schedule meetings/focus blocks, update events, and RSVP directly from the chat

### Planner Dashboard
- **Unified schedule view**: See all your Todoist tasks and Google Calendar events in one place
- **Multi-calendar support**: Select which calendars to include (work, personal, shared calendars)
- **Smart organization**: Today, Tomorrow, and This Week sections with overdue task detection
- **Priority indicators**: Visual badges for P1-P4 tasks with progressive prominence
- **Calendar labels**: Events from non-primary calendars show their calendar name as a badge
- **Interactive elements**: One-click copy, location links to Google Maps, collapsible sections
- **Proactive AI analysis**: AI automatically analyzes your schedule and provides insights
- **Real-time sync**: Refresh button fetches latest data; reset button clears and triggers fresh analysis

### Autonomous Agents
- **Scheduled execution**: Create agents that run automatically on cron schedules
- **Command Center**: Dashboard showing all agents, pending approvals, and recent activity
- **Approval workflow**: Dangerous operations (task creation, calendar events, code execution) require user approval
- **Agent-to-agent communication**: Agents can trigger other agents for multi-step workflows
- **Tool permissions**: Control which tools each agent can use
- **Dedicated conversations**: Each agent has its own conversation showing activity and history

### Personalization
- **User memory**: AI learns and remembers facts about you across conversations (viewable/deletable via brain icon)
- **Custom instructions**: Customize AI behavior via settings (e.g., "respond in Czech", "be concise")
- **User context**: Location-aware responses with appropriate units, currency, and local recommendations

### Conversation Management
- Multiple conversations with history
- **Full-text search**: Search across all conversations and messages with highlighted results
- **Deep linking**: Bookmarkable URLs for specific conversations (`#/conversations/{id}`)
- **Real-time sync**: Multi-device/tab synchronization with unread message badges
- **Infinite scroll**: Cursor-based pagination for conversations and messages
- **Copy messages**: One-click copy button on messages with rich text support

### UI & Experience
- **Color scheme**: Light, Dark, and System modes with instant switching
- **Version update banner**: Automatic detection of new deployments with reload prompt
- **Cost tracking**: Track API costs per conversation and per month with currency conversion
- Mobile-first responsive design
- **Voice input**: Speech-to-text using Web Speech API (Chrome, Safari), with language selection
- **Touch gestures**: Swipe left on conversations to rename/delete, swipe from left edge to open sidebar
- **Error handling**: Toast notifications, retry on network errors, draft message preservation
- iOS Safari and PWA compatible

### Authentication & Security
- Google Sign In authentication with email whitelist
- Local development mode (no auth required)
- **Rate limiting**: Per-user/per-IP rate limits to prevent abuse and protect against runaway clients

## Tech Stack

- **Backend**: Python 3, Flask, LangGraph/LangChain
- **Frontend**: TypeScript, Vite, Zustand
- **Database**: SQLite
- **Auth**: Google Identity Services (GIS) + JWT tokens

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ and npm
- Git LFS (for visual test screenshots)
- Google Gemini API key ([Get one here](https://aistudio.google.com/apikey))
- (Optional) Google Cloud project for authentication

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/ai-chatbot.git
cd ai-chatbot

# Setup virtual environment and install dependencies
make setup

# Copy environment template
cp .env.example .env
```

### Configuration

Edit `.env` with your settings:

```bash
# Required
GEMINI_API_KEY=your-gemini-api-key

# For local development (no auth)
FLASK_ENV=development

# For production with Google Sign In
FLASK_ENV=production
GOOGLE_CLIENT_ID=your-client-id
JWT_SECRET_KEY=your-secret-key
ALLOWED_EMAILS=user1@gmail.com,user2@gmail.com

# File upload limits (optional)
MAX_FILE_SIZE=20971520              # 20 MB in bytes
MAX_FILES_PER_MESSAGE=10
ALLOWED_FILE_TYPES=image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain,text/markdown,application/json,text/csv

# Code execution sandbox (optional, requires Docker)
CODE_SANDBOX_ENABLED=true                    # Enable/disable code execution
CODE_SANDBOX_IMAGE=ai-chatbot-sandbox:local  # Custom image (build with: make sandbox-image)
CODE_SANDBOX_TIMEOUT=30                      # Execution timeout in seconds
CODE_SANDBOX_MEMORY_LIMIT=512m               # Container memory limit
CODE_SANDBOX_LIBRARIES=numpy,pandas,matplotlib,scipy,sympy,pillow,reportlab,fpdf2

# Gunicorn settings (optional)
GUNICORN_WORKERS=2                  # Number of worker processes
GUNICORN_TIMEOUT=300                # 5 minutes default
SSE_KEEPALIVE_INTERVAL=15           # Heartbeat interval for streaming

# Cost tracking (optional)
COST_CURRENCY=CZK                   # Display currency (USD, CZK, EUR, GBP)

# User context (optional)
USER_LOCATION=Prague, Czech Republic  # For localized units, currency, recommendations

# Rate limiting (optional)
RATE_LIMITING_ENABLED=true            # Enable/disable rate limiting
RATE_LIMIT_STORAGE_URI=memory://      # Storage backend (memory://, redis://host:port)
RATE_LIMIT_DEFAULT=200 per minute     # Default limit for all endpoints
RATE_LIMIT_AUTH=10 per minute         # Auth endpoints (brute force protection)
RATE_LIMIT_CHAT=30 per minute         # Chat endpoints (expensive LLM calls)
RATE_LIMIT_CONVERSATIONS=60 per minute  # Conversation CRUD
RATE_LIMIT_FILES=120 per minute       # File downloads

# Todoist integration (optional)
TODOIST_CLIENT_ID=your-todoist-client-id
TODOIST_CLIENT_SECRET=your-todoist-client-secret
TODOIST_REDIRECT_URI=http://localhost:5173  # Your app URL (OAuth redirects here, use Vite port in dev)

# Google Calendar integration (optional)
GOOGLE_CALENDAR_CLIENT_ID=your-google-oauth-client-id
GOOGLE_CALENDAR_CLIENT_SECRET=your-google-client-secret
GOOGLE_CALENDAR_REDIRECT_URI=http://localhost:5173  # Same origin as your frontend
```

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

```bash
make            # Show available targets
make setup      # Create venv and install dependencies (Python + Node.js)
make dev        # Run Flask + Vite dev servers concurrently (with HMR)
make build      # Build frontend for production
make run        # Run Flask server (production mode)
make lint       # Run ruff, mypy, and ESLint
make lint-fix   # Auto-fix linting issues
make test       # Run all tests
make test-unit  # Run unit tests only
make test-integration  # Run integration tests only
make test-cov   # Run tests with coverage report
make deploy     # Deploy systemd service (Linux) - full restart
make reload     # Graceful reload - zero downtime (backend only)
make update     # Full update with deps rebuild + graceful reload
make vacuum     # Run database vacuum (reclaim space)
make update-currency  # Update currency exchange rates
make backup     # Create database backup manually
make backup-list  # List existing database backups
make defrag-memories  # Run memory defragmentation (consolidate user memories)
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

A nightly systemd timer consolidates and cleans up user memories using an LLM. This merges related memories, removes duplicates, and keeps memory banks efficient.

```bash
# View defrag logs
journalctl --user -u ai-chatbot-memory-defrag

# Run defragmentation manually
make defrag-memories

# Preview changes without applying (dry run)
make defrag-memories -- --dry-run
```

Only users with 50+ memories are processed by default.

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
│   ├── app.py                    # Flask entry point, Vite manifest loading
│   ├── config.py                 # Environment config
│   ├── templates/
│   │   └── index.html            # Jinja2 shell (meta tags, asset injection)
│   ├── auth/                     # Google Sign In + JWT authentication
│   ├── api/                      # REST API routes
│   ├── agent/                    # LangGraph agent and tools
│   ├── db/                       # SQLite models
│   └── utils/                    # Utilities (image processing)
├── web/                          # Vite + TypeScript frontend
│   ├── vite.config.ts            # Vite config with Flask proxy
│   ├── tsconfig.json             # TypeScript config
│   ├── package.json              # Frontend dependencies
│   └── src/
│       ├── main.ts               # Entry point
│       ├── types/                # TypeScript interfaces
│       ├── api/                  # API client
│       ├── auth/                 # Google Sign-In
│       ├── state/                # Zustand store
│       ├── components/           # UI modules
│       ├── gestures/             # Touch handlers
│       ├── utils/                # DOM, markdown, icons
│       └── styles/               # CSS
├── static/                       # Build output + PWA assets
│   ├── assets/                   # Vite output (hashed JS/CSS)
│   └── manifest.json             # PWA manifest
├── scripts/                      # Utility scripts
│   ├── vacuum_databases.py       # Database vacuum script
│   ├── update_currency_rates.py  # Currency rate update script
│   ├── backup_databases.py       # Database backup script
│   └── defragment_memories.py    # Memory defragmentation script
├── systemd/                      # Systemd service files
│   ├── ai-chatbot.service        # Main application service
│   ├── ai-chatbot-vacuum.*       # Weekly database vacuum
│   ├── ai-chatbot-currency.*     # Daily currency rate updates
│   ├── ai-chatbot-backup.*       # Daily database backups
│   └── ai-chatbot-memory-defrag.* # Nightly memory defragmentation
├── Makefile                      # Build and run targets
├── pyproject.toml                # Python project configuration
└── requirements.txt              # Python dependencies
```

## License

MIT
