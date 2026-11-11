"""The Quick actions sheet's setup Review for program conversations.

The coach reviews its own setup - quick actions and standing instructions -
against the program chat's latest turns and returns suggestions; the sheet
shows them and the user accepts or rejects each one. Nothing here posts into
the chat (docs/superpowers/specs/2026-11-11-program-self-tuning-design.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.program_review import refresh_suggestion, review_setup
from src.api.errors import raise_conflict_error, raise_not_found_error, raise_validation_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.schemas.programs import SetupChangeRequest, SetupReviewResponse
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.db.models import User
from src.services import program_setup as setup
from src.services.program_setup import (
    ProgramRef,
    SetupChange,
    SetupChangeError,
    SetupConflictError,
)

if TYPE_CHECKING:
    from apiflask import APIBlueprint

    from src.api.routes.programs import ProgramRoutesConfig


def _program_ref(user: User, namespace: str, program_id: str) -> ProgramRef:
    """The user's program, or a 404."""
    ref = ProgramRef(namespace, program_id)
    try:
        setup.load_setup(user.id, ref)
    except SetupChangeError:
        raise_not_found_error("Program")
    return ref


def _checked(ref: ProgramRef, data: SetupChangeRequest) -> SetupChange:
    checked = setup.validate_change(ref.namespace, data.change)
    if isinstance(checked, str):
        raise_validation_error(checked, field="change")
    return checked


def register_setup_review_routes(api: APIBlueprint, cfg: ProgramRoutesConfig) -> None:
    """Register POST /{ns}/programs/<program_id>/setup-review (+ /apply, /reject)."""
    from src.api.routes.programs import get_programs, program_to_item  # noqa: PLC0415 - cycle: programs imports this module

    ns = cfg.namespace

    @api.route(f"/{ns}/programs/<program_id>/setup-review", methods=["POST"])
    @api.output(SetupReviewResponse)
    @api.doc(responses=[401, 404, 429])
    @rate_limit_conversations
    @require_auth
    def review_program_setup(user: User, program_id: str) -> dict[str, object]:
        """Suggested changes to the program's quick actions and instructions."""
        ref = _program_ref(user, ns, program_id)
        return {"suggestions": review_setup(user.id, ref)}

    @api.route(f"/{ns}/programs/<program_id>/setup-review/apply", methods=["POST"])
    @api.output(cfg.programs_response)
    @api.doc(responses=[400, 401, 404, 429])
    @rate_limit_conversations
    @require_auth
    @validate_request(SetupChangeRequest)
    def apply_program_setup_change(
        user: User, data: SetupChangeRequest, program_id: str
    ) -> dict[str, object]:
        """Apply one accepted suggestion; returns the program (its quick actions)."""
        ref = _program_ref(user, ns, program_id)
        change = _checked(ref, data)
        try:
            setup.apply_change(user.id, ref, change)
        except SetupConflictError as e:
            # Not a dead end: the same change against the setup as it is now
            setup.log_resolved("review", "conflict", change)
            refreshed = refresh_suggestion(user.id, ref, change, data.summary, data.evidence)
            if refreshed is None:
                raise_validation_error(
                    "That no longer applies - nothing was changed.", field="change"
                )
            raise_conflict_error(str(e), {"suggestion": refreshed})
        except SetupChangeError as e:
            setup.log_resolved("review", "failed", change)
            raise_validation_error(str(e), field="change")
        setup.log_resolved("review", "approved", change)
        program = next(p for p in get_programs(user.id, ns) if p["id"] == program_id)
        return {"programs": [program_to_item(user.id, ns, program)]}

    @api.route(f"/{ns}/programs/<program_id>/setup-review/reject", methods=["POST"])
    @api.doc(responses=[204, 400, 401, 404, 429])
    @rate_limit_conversations
    @require_auth
    @validate_request(SetupChangeRequest)
    def reject_program_setup_change(
        user: User, data: SetupChangeRequest, program_id: str
    ) -> tuple[str, int]:
        """Reject one suggestion: remembered, so it is not suggested again without new turns."""
        ref = _program_ref(user, ns, program_id)
        change = _checked(ref, data)
        setup.record_decline(user.id, ref, change, data.summary)
        setup.log_resolved("review", "declined", change)
        return "", 204
