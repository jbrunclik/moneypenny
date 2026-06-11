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
from typing import Any

from apiflask import APIBlueprint
from apiflask.schemas import Schema

from src.api.errors import raise_not_found_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ProgramRoutesConfig:
    """Everything that differs between program features' routes."""

    namespace: str  # K/V namespace + url segment ("sports")
    display_name: str  # For log/docstrings ("Sports")
    kv_suffixes: tuple[str, ...]  # Per-program K/V keys cleaned on delete
    programs_response: type[Schema]
    conversation_response: type[Schema]
    reset_response: type[Schema]
    status_response: type[Schema]
    create_request: type[Any]  # Pydantic request model


def _slugify(name: str) -> str:
    """Convert a program name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "program"


def _get_programs(user_id: str, namespace: str) -> list[dict[str, Any]]:
    """Read programs list from KV store."""
    raw = db.kv_get(user_id, namespace, "programs")
    if not raw:
        return []
    try:
        result: list[dict[str, Any]] = json.loads(raw)
        return result
    except (json.JSONDecodeError, TypeError):
        return []


def _save_programs(user_id: str, namespace: str, programs: list[dict[str, Any]]) -> None:
    """Write programs list to KV store."""
    db.kv_set(user_id, namespace, "programs", json.dumps(programs))


def register_program_routes(api: APIBlueprint, cfg: ProgramRoutesConfig) -> None:
    """Register the 5 program-feature endpoints on the given blueprint."""
    ns = cfg.namespace

    @api.route(f"/{ns}/programs", methods=["GET"])
    @api.output(cfg.programs_response)
    @api.doc(responses=[401, 429])
    @rate_limit_conversations
    @require_auth
    def list_programs(user: User) -> dict[str, Any]:
        """List user's programs."""
        programs = _get_programs(user.id, ns)

        # Check which programs have conversations
        convs = db.list_program_conversations(ns, user.id)
        from src.db.models.programs import PROGRAM_FEATURES

        program_column = PROGRAM_FEATURES[ns].program_column
        conv_programs = {getattr(c, program_column) for c in convs}

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

    @api.route(f"/{ns}/programs", methods=["POST"])
    @api.output(cfg.programs_response)
    @api.doc(responses=[400, 401, 429])
    @rate_limit_conversations
    @require_auth
    @validate_request(cfg.create_request)
    def create_program(user: User, data: Any) -> dict[str, Any]:
        """Create a new program."""
        from datetime import datetime

        programs = _get_programs(user.id, ns)

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
        _save_programs(user.id, ns, programs)

        logger.info(
            "Program created",
            extra={"namespace": ns, "user_id": user.id, "program_id": program_id},
        )

        return {"programs": [{"has_conversation": False, **new_program}]}

    @api.route(f"/{ns}/programs/<program_id>", methods=["DELETE"])
    @api.output(cfg.status_response)
    @api.doc(responses=[401, 404, 429])
    @rate_limit_conversations
    @require_auth
    def delete_program(user: User, program_id: str) -> dict[str, Any]:
        """Delete a program and its conversation."""
        programs = _get_programs(user.id, ns)
        new_programs = [p for p in programs if p["id"] != program_id]
        if len(new_programs) == len(programs):
            raise_not_found_error("Program")

        _save_programs(user.id, ns, new_programs)

        # Delete associated conversation
        db.delete_program_conversation(ns, user.id, program_id)

        # Clean up KV data for this program
        for suffix in cfg.kv_suffixes:
            db.kv_delete(user.id, ns, f"{program_id}:{suffix}")

        logger.info(
            "Program deleted",
            extra={"namespace": ns, "user_id": user.id, "program_id": program_id},
        )

        return {"status": "deleted"}

    @api.route(f"/{ns}/<program>/conversation", methods=["GET"])
    @api.output(cfg.conversation_response)
    @api.doc(responses=[401, 404, 429])
    @rate_limit_conversations
    @require_auth
    def get_conversation(user: User, program: str) -> dict[str, Any]:
        """Get or create the program conversation."""
        from src.api.routes.planner import _optimize_messages_for_response

        # Verify program exists
        programs = _get_programs(user.id, ns)
        program_data = next((p for p in programs if p["id"] == program), None)
        if not program_data:
            raise_not_found_error("Program")

        conv = db.get_or_create_program_conversation(
            ns, user.id, program, model=Config.DEFAULT_MODEL
        )

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

    @api.route(f"/{ns}/<program>/reset", methods=["POST"])
    @api.output(cfg.reset_response)
    @api.doc(responses=[401, 404, 429])
    @rate_limit_conversations
    @require_auth
    def reset_conversation(user: User, program: str) -> dict[str, Any]:
        """Reset the program conversation (delete messages)."""
        # Verify program exists
        programs = _get_programs(user.id, ns)
        if not any(p["id"] == program for p in programs):
            raise_not_found_error("Program")

        result = db.reset_program_conversation(ns, user.id, program)
        if not result:
            raise_not_found_error(f"{cfg.display_name} conversation")

        return {
            "success": True,
            "message": f"{cfg.display_name} conversation reset successfully",
        }
