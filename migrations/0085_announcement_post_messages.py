"""What's new: each announcement post remembers its message, so an edited
announcement file revises the posted text in place.

Existing posts are paired with the first What's new message created at or
after the claim (within a minute): each post is claimed just before its
message is inserted, and the next claim comes after that insert, so this
holds even for posts milliseconds apart. Timestamps are fixed-width UTC, so
they compare as strings. A post whose chat was deleted since keeps none.
"""

from yoyo import step

__depends__ = {"0084_message_costs_stopped_by"}

steps = [
    step(
        "ALTER TABLE announcement_posts ADD COLUMN message_id TEXT",
        "ALTER TABLE announcement_posts DROP COLUMN message_id",
    ),
    step(
        """UPDATE announcement_posts SET message_id = (
               SELECT m.id FROM messages m
               JOIN conversations c ON c.id = m.conversation_id
               WHERE c.user_id = announcement_posts.user_id
                 AND c.is_whats_new = 1
                 AND m.role = 'assistant'
                 AND m.created_at >= announcement_posts.posted_at
                 AND julianday(m.created_at) - julianday(announcement_posts.posted_at)
                     < 60.0 / 86400
               ORDER BY m.created_at, m.rowid
               LIMIT 1
           )""",
        "SELECT 1",
    ),
]
