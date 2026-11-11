"""Settings' instructions Review, on settings.api.

The assistant reviews the user's custom instructions and the memories on their
border against the user's latest ordinary turns and returns suggestions;
Settings shows them and the user accepts or rejects each one. Nothing here
posts into a chat (docs/superpowers/specs/2026-11-11-instructions-self-tuning-design.md).
"""

from __future__ import annotations

from src.agent.instructions_review import refresh_suggestion, review_instructions
from src.api.errors import raise_conflict_error, raise_validation_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.routes.settings import api
from src.api.schemas.programs import SetupChangeRequest, SetupReviewResponse
from src.api.schemas.settings import InstructionsChangeResponse
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.db.models import User
from src.services import instructions_tuning as it


def _checked(data: SetupChangeRequest) -> it.InstructionChange:
    checked = it.validate_change(data.change)
    if isinstance(checked, str):
        raise_validation_error(checked, field="change")
    return checked


@api.route("/users/me/instructions-review", methods=["POST"])
@api.output(SetupReviewResponse)
@api.doc(responses=[401, 429])
@rate_limit_conversations
@require_auth
def review_custom_instructions(user: User) -> dict[str, object]:
    """Suggested changes to the custom instructions and the memories on their border."""
    return {"suggestions": review_instructions(user.id)}


@api.route("/users/me/instructions-review/apply", methods=["POST"])
@api.output(InstructionsChangeResponse)
@api.doc(responses=[400, 401, 409, 429])
@rate_limit_conversations
@require_auth
@validate_request(SetupChangeRequest)
def apply_instructions_change(user: User, data: SetupChangeRequest) -> dict[str, object]:
    """Apply one accepted suggestion; returns the instructions as they now are."""
    change = _checked(data)
    try:
        text = it.apply_change(user.id, change)
    except it.InstructionsConflictError as e:
        # Not a dead end when it can be rebuilt against the current state
        it.log_resolved("review", "conflict", change)
        refreshed = refresh_suggestion(user.id, change, data.summary, data.evidence)
        if refreshed is None:
            raise_validation_error("That no longer applies - nothing was changed.", field="change")
        raise_conflict_error(str(e), {"suggestion": refreshed})
    except it.InstructionsChangeError as e:
        it.log_resolved("review", "failed", change)
        raise_validation_error(str(e), field="change")
    it.log_resolved("review", "approved", change)
    return {"custom_instructions": text}


@api.route("/users/me/instructions-review/reject", methods=["POST"])
@api.doc(responses=[204, 400, 401, 429])
@rate_limit_conversations
@require_auth
@validate_request(SetupChangeRequest)
def reject_instructions_change(user: User, data: SetupChangeRequest) -> tuple[str, int]:
    """Reject one suggestion: remembered, so it is not suggested again without new turns."""
    change = _checked(data)
    it.record_decline(user.id, change, data.summary)
    it.log_resolved("review", "declined", change)
    return "", 204
