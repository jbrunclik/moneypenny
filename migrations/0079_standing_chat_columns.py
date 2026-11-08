"""A standing chat's own settings: its name, standing instructions and type.

An agent's goals move from autonomous_agents onto its chat (0080 copies them),
with its description and unread marker (standing_viewed_at).
standing_instructions NULL with a standing_type means the stock prompt from
code (the Daily Briefing); the first edit stores the user's own copy.
docs/superpowers/plans/2026-11-08-standing-chats-phase-2.md (Part B).
"""

from yoyo import step

__depends__ = {"0078_standing_jobs"}

steps = [
    step(
        f"ALTER TABLE conversations ADD COLUMN {name} TEXT",
        f"ALTER TABLE conversations DROP COLUMN {name}",
    )
    for name in (
        "standing_name",
        "standing_instructions",
        "standing_type",
        "standing_description",
        "standing_viewed_at",
    )
]
