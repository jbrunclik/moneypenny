#!/usr/bin/env python3
"""Agent scheduler for production deployment.

This script runs via systemd timer every minute to check for and execute
scheduled autonomous agents.

Usage:
    ./scripts/run_agent_scheduler.py

The scheduler:
1. Gets all agents due for execution (where next_run_at <= now)
2. Skips agents with pending approval requests
3. Executes each due agent
4. Updates next_run_at based on the cron schedule
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Initialize the Flask app context for database access
from src.app import create_app

# Never migrates: the new web workers do, after the deploy's backup
app = create_app(apply_migrations=False)


def main() -> None:
    """Run the agent scheduler (skipped while migrations are pending)."""
    from src.agent.scheduler import run_scheduled_agents
    from src.db.models import skip_if_migrations_pending

    if skip_if_migrations_pending("agent-scheduler"):
        return
    with app.app_context():
        run_scheduled_agents()


if __name__ == "__main__":
    main()
