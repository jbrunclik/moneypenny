"""
Heal briefing agents whose tool permissions were emptied by the editor trap.

Before commit 8f6d6f0 the agent editor rendered unrestricted (NULL)
tool_permissions as all-unchecked and saved them back as '[]' -
silently stripping every integration. The Daily Briefing agent is
system-managed and needs its tools; restore unrestricted access where
the trap hit. Regular agents are left alone ('[]' there may be an
intentional restriction).
"""

from yoyo import step

__depends__ = {"0039_add_agent_system_type"}

steps = [
    step(
        """UPDATE autonomous_agents
           SET tool_permissions = NULL
           WHERE system_type = 'daily_briefing' AND tool_permissions = '[]'""",
    ),
]
