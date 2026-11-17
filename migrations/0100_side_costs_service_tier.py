"""The Gemini service tier of a side call: 'flex' for half-price Flex calls
(the memory review, Nov 2026), NULL for standard."""

from yoyo import step

__depends__ = {"0099_memory_expiry_and_previous"}

steps = [
    step(
        "ALTER TABLE side_costs ADD COLUMN service_tier TEXT",
        "ALTER TABLE side_costs DROP COLUMN service_tier",
    ),
]
