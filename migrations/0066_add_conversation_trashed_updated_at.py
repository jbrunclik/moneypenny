"""Remember a conversation's updated_at while it is in the trash.

Trashing bumps updated_at (the trash list sorts and pages by it, most
recently deleted first); restoring puts the remembered value back, so an
Undo - above all of a bulk delete - returns chats to their place in the list
instead of lumping them at the top.
"""

from yoyo import step

__depends__ = {"0065_add_artifacts"}

steps = [
    step(
        "ALTER TABLE conversations ADD COLUMN trashed_updated_at TEXT",
        "ALTER TABLE conversations DROP COLUMN trashed_updated_at",
    ),
]
