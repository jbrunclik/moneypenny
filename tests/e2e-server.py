#!/usr/bin/env python3
"""E2E test server with mocked external services.

This server runs Flask with all external dependencies mocked (LLM, search, etc.).
Playwright auto-starts this server via webServer config. The server itself
lives in tests/e2e_server/ (settings, fakes, patches, /test/* routes, app).

Usage:
    python tests/e2e-server.py
"""

import faulthandler
import sys
from pathlib import Path

# A CI run died with a bare 'Segmentation fault (core dumped)' (Jun 2026,
# one-off). If a native crash recurs, dump Python-level tracebacks of all
# threads so the crashing call site is identifiable from the run log.
faulthandler.enable()

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Sets the test environment before any src module is imported
from tests.e2e_server import settings  # noqa: E402, F401 - imported for its side effect, after the path insert
from tests.e2e_server.app import main  # noqa: E402 - needs the path insert and settings above

if __name__ == "__main__":
    main()
