# AI Chatbot

A personal AI chatbot web application using Google Gemini APIs, similar to ChatGPT.

## Screenshots

<p align="center">
  <img src="web/tests/visual/chat.visual.ts-snapshots/conversation-with-messages-chromium-darwin.png" alt="Desktop chat interface" width="600">
</p>

<p align="center">
  <img src="web/tests/visual/chat.visual.ts-snapshots/sidebar-conversations-chromium-darwin.png" alt="Sidebar with conversations" width="280">
  <img src="web/tests/visual/mobile.visual.ts-snapshots/mobile-sidebar-open-chromium-darwin.png" alt="Mobile layout" width="200">
</p>

<sub>Screenshots from visual regression tests - always up-to-date with the latest UI.</sub>

## Features

- Chat with Google Gemini AI models (Pro and Flash)
- **Streaming responses**: Real-time token-by-token display (toggleable) with thinking indicator showing model processing and tool activity
- **File uploads**: Images, PDFs, and text files with multimodal AI analysis
- **Image generation**: Generate images from text descriptions using Gemini
- **Image lightbox**: Click thumbnails to view full-size images, with loading indicator and on-demand thumbnail loading
- **Web tools**: Real-time web search (DuckDuckGo) and URL fetching
- **Code execution**: Secure Python sandbox for calculations, data analysis, and generating PDFs/charts
- Multiple conversations with history
- Model selection (Gemini 3 Pro for complex tasks, Flash for speed)
- Markdown rendering with syntax highlighting
- **Copy messages**: One-click copy button on messages (excludes file attachments)
- **Version update banner**: Automatic detection of new deployments with reload prompt
- **Cost tracking**: Track API costs per conversation and per month with currency conversion
- Google Sign In authentication with email whitelist
- Modern dark theme, mobile-first responsive design
- **Voice input**: Speech-to-text using Web Speech API (Chrome, Safari), with language selection
- **Touch gestures**: Swipe left on conversations to delete, swipe from left edge to open sidebar
- **Error handling**: Toast notifications, retry on network errors, draft message preservation
- iOS Safari and PWA compatible
- Local development mode (no auth required)

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
CODE_SANDBOX_ENABLED=true           # Enable/disable code execution
CODE_SANDBOX_TIMEOUT=30             # Execution timeout in seconds
CODE_SANDBOX_MEMORY_LIMIT=512m      # Container memory limit
CODE_SANDBOX_IMAGE=python:3.11-slim-trixie  # Docker image (use Docker Hub to avoid auth issues)
CODE_SANDBOX_LIBRARIES=numpy,pandas,matplotlib,scipy,sympy,pillow,reportlab

# Gunicorn settings (optional)
GUNICORN_WORKERS=2                  # Number of worker processes
GUNICORN_TIMEOUT=300                # 5 minutes default
SSE_KEEPALIVE_INTERVAL=15           # Heartbeat interval for streaming

# Cost tracking (optional)
COST_CURRENCY=CZK                   # Display currency (USD, CZK, EUR, GBP)
```

### Setting up Code Execution (Docker)

The code execution feature allows the AI to run Python code in a secure, isolated Docker container. This is optional but enables powerful capabilities like data analysis, chart generation, and PDF creation.

**Prerequisites:**
- Docker installed and running
- User must have access to the Docker socket

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

### Setting up Google Sign In

To enable authentication (required for production):

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a new project (or select an existing one)
3. Click **Create Credentials** → **OAuth client ID**
4. Select **Web application** as the application type
5. Add **Authorized JavaScript origins**:
   - `http://localhost:8000` (for development)
   - `https://yourdomain.com` (for production)
6. Copy the **Client ID** to your `.env` file

No client secret is needed - the app uses Google Identity Services which validates tokens server-side.

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
make deploy     # Deploy systemd service (Linux)
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
├── Makefile                      # Build and run targets
├── pyproject.toml                # Python project configuration
└── requirements.txt              # Python dependencies
```

## License

MIT