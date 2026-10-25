"""At most one planner conversation per user.

get_or_create_planner_conversation looked before it inserted, so two first
opens at once (two devices or tabs) each created a planner, and each device
kept a different one. The index makes the second insert a no-op instead.

A database that already has duplicates keeps each user's oldest planner; the
others become ordinary conversations (messages kept) so the index can build.
"""

from yoyo import step

__depends__ = {"0067_add_search_index_keys"}

steps = [
    step(
        """UPDATE conversations SET is_planning = 0
           WHERE is_planning = 1 AND id NOT IN (
               SELECT id FROM (
                   SELECT id, ROW_NUMBER() OVER (
                       PARTITION BY user_id ORDER BY created_at, id
                   ) AS n
                   FROM conversations WHERE is_planning = 1
               ) WHERE n = 1
           )""",
        # irreversible: demoted duplicates can't be told apart from ordinary chats
        None,
    ),
    step(
        "CREATE UNIQUE INDEX idx_conversations_one_planner ON conversations(user_id) "
        "WHERE is_planning = 1",
        "DROP INDEX idx_conversations_one_planner",
    ),
]
