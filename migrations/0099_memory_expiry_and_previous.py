"""Memories can expire (valid_until, a local date: "until Friday") and keep
the text they had before their last change (previous_content), so a merge or
rewrite that lost a detail can be undone. A trigger fills previous_content on
every content change - the agent, defrag, the background review and the
instructions moves all go through it."""

from yoyo import step

__depends__ = {"0098_drop_context_cache"}

steps = [
    step(
        "ALTER TABLE user_memories ADD COLUMN valid_until TEXT",
        "ALTER TABLE user_memories DROP COLUMN valid_until",
    ),
    step(
        "ALTER TABLE user_memories ADD COLUMN previous_content TEXT",
        "ALTER TABLE user_memories DROP COLUMN previous_content",
    ),
    step(
        """CREATE TRIGGER user_memories_keep_previous
           AFTER UPDATE OF content ON user_memories
           WHEN NEW.content IS NOT OLD.content
           BEGIN
               UPDATE user_memories SET previous_content = OLD.content WHERE id = NEW.id;
           END""",
        "DROP TRIGGER user_memories_keep_previous",
    ),
]
