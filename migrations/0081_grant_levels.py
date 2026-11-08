"""Grant levels: "<tool>" lets a standing job read, "<tool>:write" also write.

Until now a granted tool allowed writes (destructive operations aside). So a
job that already has a writable tool gets its write level too: nothing it
could do changes. New grants start read-only; a write without the level is a
draft the user approves. docs/superpowers/plans/2026-11-08-standing-chats-phase-2.md (D3).
"""

import json

from yoyo import step

__depends__ = {"0080_agents_to_standing_jobs"}

# As of this migration (src/agent/permissions.py WRITE_LEVEL_TOOLS)
_WRITABLE = ("todoist", "google_calendar", "garmin_workout", "rouvy_workout")
_SUFFIX = ":write"


def _rewrite(conn, change) -> None:  # type: ignore[no-untyped-def]
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT id, grants FROM scheduled_items WHERE grants IS NOT NULL"
    ).fetchall()
    for item_id, raw in rows:
        grants = json.loads(raw)
        updated = change(grants)
        if updated != grants:
            cursor.execute(
                "UPDATE scheduled_items SET grants = ? WHERE id = ?", (json.dumps(updated), item_id)
            )


def add_write_levels(conn) -> None:  # type: ignore[no-untyped-def]
    def change(grants: list[str]) -> list[str]:
        writes = [f"{tool}{_SUFFIX}" for tool in _WRITABLE if tool in grants]
        return list(dict.fromkeys([*grants, *writes]))

    _rewrite(conn, change)


def strip_write_levels(conn) -> None:  # type: ignore[no-untyped-def]
    _rewrite(conn, lambda grants: [g for g in grants if not g.endswith(_SUFFIX)])


steps = [step(add_write_levels, strip_write_levels)]
