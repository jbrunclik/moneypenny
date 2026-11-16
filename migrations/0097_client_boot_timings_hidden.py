"""Whether the page went to the background before startup finished. A phone
backgrounded mid-start reports minutes, not seconds: those rows stay (they
happened) but are flagged, so the startup medians can leave them out."""

from yoyo import step

__depends__ = {"0096_client_boot_timings"}

steps = [
    step(
        "ALTER TABLE client_boot_timings ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE client_boot_timings DROP COLUMN hidden",
    ),
]
