"""Program-conversation context loaders (sports, language).

Loads the program metadata and stored KV data that the system prompt's
dynamic context carries for program conversations.
"""

from __future__ import annotations

import json
from typing import Any

from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)


def load_sports_context(user_id: str, program_id: str) -> dict[str, Any] | None:
    """Load sports program context from K/V store for the system prompt.

    Loads the program metadata AND any existing KV data (goals, preferences,
    routine, progress, last_session) so the agent can see what's stored.

    Args:
        user_id: The user's ID
        program_id: The sports program ID

    Returns:
        Sports context dict with program info and stored KV data, or None
    """
    raw = db.kv_get(user_id, "sports", "programs")
    if not raw:
        return None
    try:
        programs = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    program = next((p for p in programs if p.get("id") == program_id), None)
    if not program:
        return None

    # Load existing KV data for this program (single query with prefix)
    items = db.kv_list(user_id, "sports", prefix=f"{program_id}:")
    kv_data = {k.split(":", 1)[1]: v for k, v in items}

    return {
        "program_name": program.get("name", "Training"),
        "program_id": program_id,
        "kv_data": kv_data,
    }


def load_language_context(user_id: str, program_id: str) -> dict[str, Any] | None:
    """Load language program context from K/V store for the system prompt.

    Loads the program metadata AND any existing KV data (profile, assessment,
    vocabulary, grammar, etc.) so the agent can see what's stored.

    Args:
        user_id: The user's ID
        program_id: The language program ID

    Returns:
        Language context dict with program info and stored KV data, or None
    """
    raw = db.kv_get(user_id, "language", "programs")
    if not raw:
        return None
    try:
        programs = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    program = next((p for p in programs if p.get("id") == program_id), None)
    if not program:
        return None

    # Load existing KV data for this program (single query with prefix)
    items = db.kv_list(user_id, "language", prefix=f"{program_id}:")
    kv_data = {k.split(":", 1)[1]: v for k, v in items}

    return {
        "program_name": program.get("name", "Language"),
        "program_id": program_id,
        "kv_data": kv_data,
    }
