"""Shared route factory for program features (sports, language, ...).

Each program feature exposes the same 5 endpoints (list/create/delete
programs, get-or-create conversation, reset conversation) differing only
in url segment, K/V namespace, response schemas, and the per-program K/V
suffixes to clean up on delete. Sports and language were two near-identical
route modules; this factory is the single parameterized replacement (Q2).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from apiflask import APIBlueprint

from src.api.errors import raise_not_found_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.routes.program_quick_actions import (
    QUICK_ACTION_DEFAULTS,
    register_quick_action_routes,
    resolve_quick_actions,
)
from src.api.utils import serialize_messages_for_response
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User, db
from src.db.models.programs import PROGRAM_FEATURES
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ProgramRoutesConfig:
    """Everything that differs between program features' routes."""

    namespace: str  # K/V namespace + url segment ("sports")
    display_name: str  # For log/docstrings ("Sports")
    kv_suffixes: tuple[str, ...]  # Per-program K/V keys cleaned on delete
    # Schema classes are passed to apiflask's @api.output / validate_request;
    # typed loosely because the generated response schemas share no base class
    programs_response: type[Any]
    conversation_response: type[Any]
    reset_response: type[Any]
    status_response: type[Any]
    create_request: type[Any]  # Pydantic request model


def _slugify(name: str) -> str:
    """Convert a program name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "program"


def get_programs(user_id: str, namespace: str) -> list[dict[str, Any]]:
    """Read programs list from KV store."""
    raw = db.kv_get(user_id, namespace, "programs")
    if not raw:
        return []
    try:
        result: list[dict[str, Any]] = json.loads(raw)
        return result
    except json.JSONDecodeError, TypeError:
        return []


def save_programs(user_id: str, namespace: str, programs: list[dict[str, Any]]) -> None:
    """Write programs list to KV store."""
    db.kv_set(user_id, namespace, "programs", json.dumps(programs))


def program_to_item(
    user_id: str,
    namespace: str,
    program: dict[str, Any],
    conv_program_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Shape a stored program dict as the API's program item."""
    if conv_program_ids is None:
        column = PROGRAM_FEATURES[namespace].program_column
        conv_program_ids = {
            getattr(c, column) for c in db.list_program_conversations(namespace, user_id)
        }
    return {
        "id": program["id"],
        "name": program["name"],
        "emoji": program["emoji"],
        "created_at": program["created_at"],
        "has_conversation": program["id"] in conv_program_ids,
        "quick_actions": resolve_quick_actions(program, namespace),
    }


def _unique_program_id(slug: str, programs: list[dict[str, Any]]) -> str:
    """The slug, suffixed -2, -3, ... until no existing program has it."""
    existing_ids = {p["id"] for p in programs}
    program_id = slug
    counter = 1
    while program_id in existing_ids:
        counter += 1
        program_id = f"{slug}-{counter}"
    return program_id


def _delete_program_data(
    user_id: str, ns: str, program_id: str, kv_suffixes: tuple[str, ...]
) -> None:
    """Delete a program's conversation and its KV data."""
    # Delete associated conversation
    db.delete_program_conversation(ns, user_id, program_id)

    # Clean up KV data for this program
    for suffix in kv_suffixes:
        db.kv_delete(user_id, ns, f"{program_id}:{suffix}")


def register_program_routes(api: APIBlueprint, cfg: ProgramRoutesConfig) -> None:
    """Register the 5 program-feature endpoints on the given blueprint."""
    _register_program_crud_routes(api, cfg)
    _register_program_conversation_routes(api, cfg)
    register_quick_action_routes(api, cfg)


def _register_program_crud_routes(api: APIBlueprint, cfg: ProgramRoutesConfig) -> None:
    """List, create and delete programs."""
    ns = cfg.namespace

    @api.route(f"/{ns}/programs", methods=["GET"])
    @api.output(cfg.programs_response)
    @api.doc(responses=[401, 429])
    @rate_limit_conversations
    @require_auth
    def list_programs(user: User) -> dict[str, Any]:
        """List user's programs."""
        programs = get_programs(user.id, ns)

        # Check which programs have conversations
        convs = db.list_program_conversations(ns, user.id)

        program_column = PROGRAM_FEATURES[ns].program_column
        conv_programs = {getattr(c, program_column) for c in convs}

        return {"programs": [program_to_item(user.id, ns, p, conv_programs) for p in programs]}

    @api.route(f"/{ns}/programs", methods=["POST"])
    @api.output(cfg.programs_response)
    @api.doc(responses=[400, 401, 429])
    @rate_limit_conversations
    @require_auth
    @validate_request(cfg.create_request)
    def create_program(user: User, data: Any) -> dict[str, Any]:
        """Create a new program."""

        programs = get_programs(user.id, ns)

        program_id = _unique_program_id(_slugify(data.name), programs)
        new_program = {
            "id": program_id,
            "name": data.name,
            "emoji": data.emoji,
            "created_at": datetime.now().isoformat(),
            "quick_actions": [dict(a) for a in QUICK_ACTION_DEFAULTS.get(ns, [])],
        }
        programs.append(new_program)
        save_programs(user.id, ns, programs)

        logger.info(
            "Program created",
            extra={"namespace": ns, "user_id": user.id, "program_id": program_id},
        )

        return {"programs": [program_to_item(user.id, ns, new_program, set())]}

    @api.route(f"/{ns}/programs/<program_id>", methods=["DELETE"])
    @api.output(cfg.status_response)
    @api.doc(responses=[401, 404, 429])
    @rate_limit_conversations
    @require_auth
    def delete_program(user: User, program_id: str) -> dict[str, Any]:
        """Delete a program and its conversation."""
        programs = get_programs(user.id, ns)
        new_programs = [p for p in programs if p["id"] != program_id]
        if len(new_programs) == len(programs):
            raise_not_found_error("Program")

        save_programs(user.id, ns, new_programs)

        _delete_program_data(user.id, ns, program_id, cfg.kv_suffixes)

        logger.info(
            "Program deleted",
            extra={"namespace": ns, "user_id": user.id, "program_id": program_id},
        )

        return {"status": "deleted"}


def _register_program_conversation_routes(api: APIBlueprint, cfg: ProgramRoutesConfig) -> None:
    """Get-or-create and reset a program's conversation."""
    ns = cfg.namespace

    @api.route(f"/{ns}/<program>/conversation", methods=["GET"])
    @api.output(cfg.conversation_response)
    @api.doc(responses=[401, 404, 429])
    @rate_limit_conversations
    @require_auth
    def get_conversation(user: User, program: str) -> dict[str, Any]:
        """Get or create the program conversation."""

        # Verify program exists
        programs = get_programs(user.id, ns)
        program_data = next((p for p in programs if p["id"] == program), None)
        if not program_data:
            raise_not_found_error("Program")

        conv = db.get_or_create_program_conversation(
            ns, user.id, program, model=Config.DEFAULT_MODEL
        )

        messages = db.get_messages(conv.id)
        optimized_messages = serialize_messages_for_response(messages)

        return {
            "id": conv.id,
            "title": conv.title,
            "model": conv.model,
            "program": program,
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat(),
            "messages": optimized_messages,
        }

    @api.route(f"/{ns}/<program>/reset", methods=["POST"])
    @api.output(cfg.reset_response)
    @api.doc(responses=[401, 404, 429])
    @rate_limit_conversations
    @require_auth
    def reset_conversation(user: User, program: str) -> dict[str, Any]:
        """Reset the program conversation (delete messages)."""
        # Verify program exists
        programs = get_programs(user.id, ns)
        if not any(p["id"] == program for p in programs):
            raise_not_found_error("Program")

        result = db.reset_program_conversation(ns, user.id, program)
        if not result:
            raise_not_found_error(f"{cfg.display_name} conversation")

        return {
            "success": True,
            "message": f"{cfg.display_name} conversation reset successfully",
        }
