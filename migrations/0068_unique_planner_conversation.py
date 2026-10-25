"""At most one planner conversation per user.

get_or_create_planner_conversation looked before it inserted, so two first
opens at once (two devices or tabs) each created a planner, and each device
kept a different one. The index makes the second insert a no-op instead.
"""

from yoyo import step

__depends__ = {"0067_add_search_index_keys"}

steps = [
    step(
        "CREATE UNIQUE INDEX idx_conversations_one_planner ON conversations(user_id) "
        "WHERE is_planning = 1",
        "DROP INDEX idx_conversations_one_planner",
    ),
]
