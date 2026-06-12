"""
Add message_costs.cached_input_tokens for context-cache telemetry.

Tracks how many of input_tokens were served from Gemini's context cache
(usage_metadata.input_token_details.cache_read). Cached tokens bill at
~25% of the input rate, so recording them makes cost_usd reflect the
real bill and lets scripts/analyze_costs.py verify cache effectiveness.
Existing rows backfill to 0 (cache hits were never recorded before).
"""

from yoyo import step

__depends__ = {"0042_encrypt_tokens_at_rest"}

steps = [
    step(
        "ALTER TABLE message_costs ADD COLUMN cached_input_tokens INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE message_costs DROP COLUMN cached_input_tokens",
    ),
]
