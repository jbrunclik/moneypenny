"""A short summary per memory for the per-turn context (the full text stays
the source of truth, a search_memory id lookup away). Changing a memory's
text clears its summary - by trigger, so every write path (the tool, memory
review, the UI, the nightly defrag) is covered; the scheduler pass writes it
again (docs/superpowers/specs/2026-11-15-cost-telemetry-design.md)."""

from yoyo import step

__depends__ = {"0093_side_costs"}

steps = [
    step(
        "ALTER TABLE user_memories ADD COLUMN summary TEXT",
        "ALTER TABLE user_memories DROP COLUMN summary",
    ),
    step(
        """CREATE TRIGGER user_memories_summary_reset
           AFTER UPDATE OF content ON user_memories
           WHEN NEW.content IS NOT OLD.content
           BEGIN
               UPDATE user_memories SET summary = NULL WHERE id = NEW.id;
           END""",
        "DROP TRIGGER user_memories_summary_reset",
    ),
]
