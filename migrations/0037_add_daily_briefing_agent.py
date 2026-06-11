"""
Add users.daily_briefing_agent_id for the Settings-managed Daily Briefing.

The Daily Briefing is an ordinary autonomous agent (full executor +
scheduler + push reuse); this column is the user-level pointer that lets
Settings find/upsert it. A dangling id (agent deleted from Command
Center) is treated as "disabled" and a new agent is created on the next
enable.
"""

from yoyo import step

__depends__ = {"0036_add_push_subscriptions"}

steps = [
    step(
        "ALTER TABLE users ADD COLUMN daily_briefing_agent_id TEXT",
        "ALTER TABLE users DROP COLUMN daily_briefing_agent_id",
    ),
]
