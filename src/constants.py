"""True constants - unit conversions and mathematical constants.

These are fundamental constants that should never need to be changed.
For developer-configurable values, see config.py.

Guidelines:
- Only include truly immutable values (unit conversions)
- Use SCREAMING_SNAKE_CASE for constant names
- Include units in the constant name (e.g., _SECONDS, _BYTES)
"""

# =============================================================================
# Time Constants (Base Units)
# =============================================================================

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 60 * SECONDS_PER_MINUTE
SECONDS_PER_DAY = 24 * SECONDS_PER_HOUR
SECONDS_PER_WEEK = 7 * SECONDS_PER_DAY

# =============================================================================
# Size Constants (Base Units)
# =============================================================================

BYTES_PER_KB = 1024
BYTES_PER_MB = 1024 * BYTES_PER_KB

# =============================================================================
# Token Constants
# =============================================================================

# Tokens per million (for cost calculation)
TOKENS_PER_MILLION = 1_000_000
# =============================================================================
# Skills (src/agent/skills/<name>/SKILL.md)
# =============================================================================
SKILL_MAX_DESCRIPTION_CHARS = 300  # index entry - always in the prompt
SKILL_MAX_BODY_CHARS = 12_000  # ~3k tokens per load

# The Gemini API rejects a request deadline below this (400 INVALID_ARGUMENT,
# "Minimum allowed deadline is 10s")
GEMINI_MIN_REQUEST_DEADLINE_SECONDS = 10
