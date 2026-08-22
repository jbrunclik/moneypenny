"""
Pinned conversations: a pinned flag keeps recurring family threads (meal
planning, trips) at the top of the sidebar instead of churning away on
updated_at ordering. Pinned conversations are excluded from the paginated
list and returned separately (they're few, and pinned-first ORDER BY would
break the (updated_at, id) cursor math).
"""

from yoyo import step

__depends__ = {"0050_add_turn_metrics"}

steps = [
    step(
        "ALTER TABLE conversations ADD COLUMN pinned INTEGER DEFAULT 0",
        "ALTER TABLE conversations DROP COLUMN pinned",
    ),
]
