"""Language learning routes: Programs and conversations.

This module handles language learning programs with dedicated conversations
where the AI acts as a language tutor. Program definitions, assessment data,
and vocabulary are stored in the K/V store (namespace: language).
"""

import json
import re
from typing import Any

from apiflask import APIBlueprint

from src.api.errors import raise_not_found_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.routes.planner import _optimize_messages_for_response
from src.api.schemas import (
    CreateLanguageProgramRequest,
    LanguageConversationResponse,
    LanguageProgramsResponse,
    LanguageResetResponse,
    StatusResponse,
)
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)

api = APIBlueprint("language", __name__, url_prefix="/api", tag="Language")

_NAMESPACE = "language"


def _slugify(name: str) -> str:
    """Convert a program name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "program"


def _get_programs(user_id: str) -> list[dict[str, Any]]:
    """Read programs list from KV store."""
    raw = db.kv_get(user_id, _NAMESPACE, "programs")
    if not raw:
        return []
    try:
        result: list[dict[str, Any]] = json.loads(raw)
        return result
    except (json.JSONDecodeError, TypeError):
        return []


def _save_programs(user_id: str, programs: list[dict[str, Any]]) -> None:
    """Write programs list to KV store."""
    db.kv_set(user_id, _NAMESPACE, "programs", json.dumps(programs))


@api.route("/language/programs", methods=["GET"])
@api.output(LanguageProgramsResponse)
@api.doc(responses=[401, 429])
@rate_limit_conversations
@require_auth
def list_programs(user: User) -> dict[str, Any]:
    """List user's language learning programs."""
    programs = _get_programs(user.id)

    # Check which programs have conversations
    language_convs = db.list_language_conversations(user.id)
    conv_programs = {c.language_program for c in language_convs}

    items = []
    for p in programs:
        items.append(
            {
                "id": p["id"],
                "name": p["name"],
                "emoji": p["emoji"],
                "created_at": p["created_at"],
                "has_conversation": p["id"] in conv_programs,
            }
        )

    return {"programs": items}


@api.route("/language/programs", methods=["POST"])
@api.output(LanguageProgramsResponse)
@api.doc(responses=[400, 401, 429])
@rate_limit_conversations
@require_auth
@validate_request(CreateLanguageProgramRequest)
def create_program(user: User, data: CreateLanguageProgramRequest) -> dict[str, Any]:
    """Create a new language learning program."""
    from datetime import datetime

    programs = _get_programs(user.id)

    slug = _slugify(data.name)
    # Ensure unique ID
    existing_ids = {p["id"] for p in programs}
    program_id = slug
    counter = 1
    while program_id in existing_ids:
        counter += 1
        program_id = f"{slug}-{counter}"

    new_program = {
        "id": program_id,
        "name": data.name,
        "emoji": data.emoji,
        "created_at": datetime.now().isoformat(),
    }
    programs.append(new_program)
    _save_programs(user.id, programs)

    logger.info(
        "Language program created",
        extra={"user_id": user.id, "program_id": program_id},
    )

    return {"programs": [{"has_conversation": False, **new_program}]}


@api.route("/language/programs/<program_id>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[401, 404, 429])
@rate_limit_conversations
@require_auth
def delete_program(user: User, program_id: str) -> dict[str, Any]:
    """Delete a language program and its conversation."""
    programs = _get_programs(user.id)
    new_programs = [p for p in programs if p["id"] != program_id]
    if len(new_programs) == len(programs):
        raise_not_found_error("Program")

    _save_programs(user.id, new_programs)

    # Delete associated conversation
    db.delete_language_conversation(user.id, program_id)

    # Clean up KV data for this program
    for suffix in (
        "profile",
        "assessment",
        "vocabulary",
        "grammar",
        "weak_points",
        "session_history",
        "last_session",
        "stats",
    ):
        db.kv_delete(user.id, _NAMESPACE, f"{program_id}:{suffix}")

    logger.info(
        "Language program deleted",
        extra={"user_id": user.id, "program_id": program_id},
    )

    return {"status": "deleted"}


@api.route("/language/<program>/conversation", methods=["GET"])
@api.output(LanguageConversationResponse)
@api.doc(responses=[401, 404, 429])
@rate_limit_conversations
@require_auth
def get_language_conversation(user: User, program: str) -> dict[str, Any]:
    """Get or create a language conversation for a program."""
    # Verify program exists
    programs = _get_programs(user.id)
    program_data = next((p for p in programs if p["id"] == program), None)
    if not program_data:
        raise_not_found_error("Program")

    conv = db.get_or_create_language_conversation(user.id, program, model=Config.DEFAULT_MODEL)

    messages = db.get_messages(conv.id)
    optimized_messages = _optimize_messages_for_response(messages)

    return {
        "id": conv.id,
        "title": conv.title,
        "model": conv.model,
        "program": program,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "messages": optimized_messages,
    }


@api.route("/language/<program>/reset", methods=["POST"])
@api.output(LanguageResetResponse)
@api.doc(responses=[401, 404, 429])
@rate_limit_conversations
@require_auth
def reset_language_conversation(user: User, program: str) -> dict[str, Any]:
    """Reset a language conversation (delete messages + clear checkpoint)."""
    # Verify program exists
    programs = _get_programs(user.id)
    if not any(p["id"] == program for p in programs):
        raise_not_found_error("Program")

    result = db.reset_language_conversation(user.id, program)
    if not result:
        raise_not_found_error("Language conversation")

    return {
        "success": True,
        "message": "Language conversation reset successfully",
    }
