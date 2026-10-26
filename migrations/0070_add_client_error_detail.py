"""Add detail to client_errors: the measurements of a layout check.

Layout reports (kind "layout", web/src/core/layout-checks.ts) carry no stack;
they carry which invariant broke, the build marker and a few viewport numbers,
kept as JSON so the admin page can group them per build.
"""

from yoyo import step

__depends__ = {"0069_add_client_errors"}

steps = [
    step(
        "ALTER TABLE client_errors ADD COLUMN detail TEXT",
        "ALTER TABLE client_errors DROP COLUMN detail",
    ),
]
