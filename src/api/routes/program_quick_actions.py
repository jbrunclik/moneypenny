"""Quick actions for program conversations (sports, language).

A quick action is a per-program saved prompt (emoji, label, body, optional
field labels). They live INSIDE each program object in the namespace's
``programs`` K/V list - never under the ``{program_id}:`` prefix, which
program_context.py injects into the system prompt on every turn. Defaults,
sanitizing and the limits live in src/services/program_setup.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.api.errors import raise_not_found_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.schemas.programs import UpdateQuickActionsRequest
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.db.models import User
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from apiflask import APIBlueprint

    from src.api.routes.programs import ProgramRoutesConfig

logger = get_logger(__name__)


def register_quick_action_routes(api: APIBlueprint, cfg: ProgramRoutesConfig) -> None:
    """Register PUT /{ns}/programs/<program_id>/quick-actions."""
    from src.api.routes.programs import (  # noqa: PLC0415 - cycle: programs imports this module
        get_programs,
        program_to_item,
        save_programs,
    )

    ns = cfg.namespace

    @api.route(f"/{ns}/programs/<program_id>/quick-actions", methods=["PUT"])
    @api.output(cfg.programs_response)
    @api.doc(responses=[400, 401, 404, 429])
    @rate_limit_conversations
    @require_auth
    @validate_request(UpdateQuickActionsRequest)
    def update_quick_actions(user: User, data: Any, program_id: str) -> dict[str, Any]:
        """Replace the program's quick actions (create/edit/reorder/delete)."""
        programs = get_programs(user.id, ns)
        program = next((p for p in programs if p["id"] == program_id), None)
        if program is None:
            raise_not_found_error("Program")

        program["quick_actions"] = [a.model_dump() for a in data.quick_actions]
        save_programs(user.id, ns, programs)

        logger.info(
            "Quick actions updated",
            extra={
                "namespace": ns,
                "user_id": user.id,
                "program_id": program_id,
                "count": len(program["quick_actions"]),
            },
        )
        return {"programs": [program_to_item(user.id, ns, program)]}
