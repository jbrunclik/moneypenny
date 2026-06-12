"""
Add autonomous_agents.fresh_context.

Fresh-context agents run every execution from a clean slate: prior runs
remain readable in the agent's conversation but are not sent to the LLM.
Saves tokens for report-style agents (Daily Briefing) whose runs are
independent. Existing agents keep history (0); new agents default to
fresh context at the application layer.
"""

from yoyo import step

__depends__ = {"0037_add_daily_briefing_agent"}

steps = [
    step(
        "ALTER TABLE autonomous_agents ADD COLUMN fresh_context INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE autonomous_agents DROP COLUMN fresh_context",
    ),
]
