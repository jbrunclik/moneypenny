"""Settings routes: user settings management.

This module contains routes for managing user settings like custom instructions.
"""

from typing import Any

from apiflask import APIBlueprint

from src.api.schemas import StatusResponse, UpdateSettingsRequest, UserSettingsResponse
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)

api = APIBlueprint("settings", __name__, url_prefix="/api", tag="Settings")


# ============================================================================
# Settings Routes
# ============================================================================


@api.route("/users/me/settings", methods=["GET"])
@api.output(UserSettingsResponse)
@require_auth
def get_user_settings(user: User) -> dict[str, Any]:
    """Get user settings including custom instructions."""
    logger.debug("Getting user settings", extra={"user_id": user.id})
    return {
        "custom_instructions": user.custom_instructions or "",
    }


@api.route("/users/me/settings", methods=["PATCH"])
@api.output(StatusResponse)
@require_auth
@validate_request(UpdateSettingsRequest)
def update_user_settings(user: User, data: UpdateSettingsRequest) -> tuple[dict[str, str], int]:
    """Update user settings."""
    logger.debug(
        "Updating user settings",
        extra={
            "user_id": user.id,
            "has_custom_instructions": data.custom_instructions is not None,
        },
    )

    if data.custom_instructions is not None:
        # Normalize empty/whitespace-only strings to None
        instructions = data.custom_instructions.strip() if data.custom_instructions else None
        db.update_user_custom_instructions(user.id, instructions)
        logger.info(
            "User settings updated",
            extra={"user_id": user.id, "has_instructions": bool(instructions)},
        )

    return {"status": "updated"}, 200
