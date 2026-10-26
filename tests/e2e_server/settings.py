"""Test environment, port and file locations - set before any `src` import."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Set test environment BEFORE importing app modules
# Use "testing" for FLASK_ENV (enables testing-specific behavior)
# Use E2E_TESTING=true to bypass auth (separate from unit tests which need auth)
os.environ["FLASK_ENV"] = "testing"
os.environ["E2E_TESTING"] = "true"  # Enable auth bypass for E2E tests
os.environ["GEMINI_API_KEY"] = "test-api-key-for-e2e"
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-e2e-testing"
os.environ["ALLOWED_EMAILS"] = "*"  # Allow all emails in E2E tests
os.environ["ADMIN_EMAILS"] = "local@localhost"  # The auth-bypass user sees the admin page
os.environ["LOG_LEVEL"] = "WARNING"  # Reduce noise during E2E tests
# No APP_URL: the artifact frame's CSP then names the origin each request
# came to (localhost or 127.0.0.1 - CI's baseline job uses the latter). A
# local .env may point APP_URL at the Vite dev server, which matches neither.
os.environ["APP_URL"] = ""
# The post-answer grounding check must never call the live API from tests;
# its own tests opt back in via monkeypatch on Config.
os.environ["GROUNDING_CHECK_ENABLED"] = "false"
# No live freshness-gate calls (src/agent/freshness.py); tests enable it explicitly
os.environ["FRESHNESS_GATE_ENABLED"] = "false"
# Metered search providers must never be billed from tests (src/config.py
# loads the real .env); evals blank the same keys (evals/run.py)
for _key in ("BRAVE_SEARCH_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "LINKUP_API_KEY"):
    os.environ[_key] = ""
os.environ["EMBEDDINGS_ENABLED"] = "false"  # No live embedding calls from E2E
os.environ["RATE_LIMITING_ENABLED"] = "false"  # Disable rate limiting for parallel tests

# E2E_PORT lets two servers run side by side (e.g. two worktrees or sessions):
# the port also scopes the PID file and every database file name below, since
# the DB directory is shared (tmpfs on Linux) and cleanup globs it.
E2E_PORT = int(os.environ.get("E2E_PORT", "8001"))

# Template databases are created once at startup with migrations applied
# Test contexts copy the template instead of running migrations for each test
# The test databases are disposable, so keep them on tmpfs where one exists
# (Linux CI runners): every commit fsyncs, and on a GitHub runner's disk the
# per-test reset (a few commits) and each chat turn were taking seconds under
# eight concurrent contexts (SLOW/INFLIGHT lines in the job log).
_SHM = Path("/dev/shm")
E2E_DB_DIR = (
    (_SHM / "moneypenny-e2e")
    if _SHM.is_dir() and os.access(_SHM, os.W_OK)
    else PROJECT_ROOT / "tests"
)
E2E_DB_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE_DB_PATH = E2E_DB_DIR / f"e2e-template-{E2E_PORT}.db"
TEMPLATE_BLOB_PATH = E2E_DB_DIR / f"e2e-template-{E2E_PORT}-blobs.db"
# Set env vars to the template path - migrations will run on template
os.environ["DATABASE_PATH"] = str(TEMPLATE_DB_PATH)
os.environ["BLOB_STORAGE_PATH"] = str(TEMPLATE_BLOB_PATH)

# PID file for cleanup
E2E_PID_FILE = PROJECT_ROOT / f".e2e-server-{E2E_PORT}.pid"
