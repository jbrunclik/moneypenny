"""Quick actions for program conversations (sports, language).

A quick action is a per-program saved prompt (emoji, label, body, optional
field labels). They live INSIDE each program object in the namespace's
``programs`` K/V list - never under the ``{program_id}:`` prefix, which
program_context.py injects into the system prompt on every turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from src.api.errors import raise_not_found_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.schemas import (
    QUICK_ACTIONS_MAX_PER_PROGRAM,
    QuickActionItem,
    UpdateQuickActionsRequest,
)
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.db.models import User
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from apiflask import APIBlueprint

    from src.api.routes.programs import ProgramRoutesConfig

logger = get_logger(__name__)

QUICK_ACTION_DEFAULTS: dict[str, list[dict[str, Any]]] = {
    "sports": [
        {
            "id": "plan-today",
            "emoji": "\U0001f4cb",
            "label": "Plan today",
            "body": (
                "Plan today's session. Check my Garmin readiness first and tell me "
                "which numbers drove the intensity call."
            ),
            "fields": ["Comments"],
        },
        {
            "id": "log-review",
            "emoji": "\U0001f4ca",
            "label": "Log & review",
            "body": (
                "Assess today's session against the plan and stored progress, note any "
                "PRs, update the Garmin workouts for the next session, and prepare the "
                "overview table."
            ),
            "fields": ["Results", "Comments"],
        },
    ],
    "language": [
        {
            "id": "new-lesson",
            "emoji": "\U0001f4d6",
            "label": "New lesson",
            "body": "Start a new lesson.",
            "fields": [],
        },
        {
            "id": "quiz-me",
            "emoji": "\U0001f9e0",
            "label": "Quiz me",
            "body": "Quiz me on the vocabulary from the last two lessons.",
            "fields": [],
        },
    ],
}


def sanitize_quick_actions(raw: Any) -> list[dict[str, Any]]:
    """Validate stored actions, dropping malformed entries instead of failing."""
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for entry in raw:
        try:
            item = QuickActionItem.model_validate(entry)
        except (ValidationError, TypeError):
            logger.warning("Dropping malformed quick action", extra={"entry": repr(entry)[:200]})
            continue
        result.append(item.model_dump())
        if len(result) >= QUICK_ACTIONS_MAX_PER_PROGRAM:
            break
    return result


def resolve_quick_actions(program: dict[str, Any], namespace: str) -> list[dict[str, Any]]:
    """Actions for a program: stored list (sanitized) or namespace defaults when absent."""
    if "quick_actions" not in program:
        return [dict(a) for a in QUICK_ACTION_DEFAULTS.get(namespace, [])]
    return sanitize_quick_actions(program["quick_actions"])


def register_quick_action_routes(api: APIBlueprint, cfg: ProgramRoutesConfig) -> None:
    """Register PUT /{ns}/programs/<program_id>/quick-actions."""
    from src.api.routes.programs import _get_programs, _save_programs, program_to_item

    ns = cfg.namespace

    @api.route(f"/{ns}/programs/<program_id>/quick-actions", methods=["PUT"])
    @api.output(cfg.programs_response)
    @api.doc(responses=[400, 401, 404, 429])
    @rate_limit_conversations
    @require_auth
    @validate_request(UpdateQuickActionsRequest)
    def update_quick_actions(user: User, data: Any, program_id: str) -> dict[str, Any]:
        """Replace the program's quick actions (create/edit/reorder/delete)."""
        programs = _get_programs(user.id, ns)
        program = next((p for p in programs if p["id"] == program_id), None)
        if program is None:
            raise_not_found_error("Program")

        program["quick_actions"] = [a.model_dump() for a in data.quick_actions]
        _save_programs(user.id, ns, programs)

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
