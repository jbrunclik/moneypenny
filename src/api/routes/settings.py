"""Settings routes: user settings management.

This module contains routes for managing user settings like custom instructions.
"""

from typing import Any

from apiflask import APIBlueprint

from src.agent.tools.whatsapp import is_whatsapp_available
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
    """Get user settings including custom instructions and WhatsApp phone."""
    logger.debug("Getting user settings", extra={"user_id": user.id})
    return {
        "custom_instructions": user.custom_instructions or "",
        "whatsapp_phone": user.whatsapp_phone,
        "whatsapp_available": is_whatsapp_available(),
    }


@api.route("/users/me/settings", methods=["PATCH"])
@api.output(StatusResponse)
@require_auth
@validate_request(UpdateSettingsRequest)
def update_user_settings(user: User, data: UpdateSettingsRequest) -> tuple[dict[str, str], int]:
    """Update user settings."""
    # Use model_fields_set to detect which fields were explicitly provided
    # This allows distinguishing between "not provided" and "provided as empty/null"
    # PATCH semantics:
    # - Field not present in request → don't change
    # - Field present with null → don't change (standard PATCH behavior)
    # - Field present with value → update (including empty string to clear)
    fields_set = data.model_fields_set

    logger.debug(
        "Updating user settings",
        extra={
            "user_id": user.id,
            "has_custom_instructions": "custom_instructions" in fields_set,
            "has_whatsapp_phone": "whatsapp_phone" in fields_set,
        },
    )

    # Custom instructions: update only if explicitly provided and not null
    if "custom_instructions" in fields_set and data.custom_instructions is not None:
        # Normalize empty/whitespace-only strings to None
        instructions = data.custom_instructions.strip() if data.custom_instructions else None
        db.update_user_custom_instructions(user.id, instructions)
        logger.info(
            "User custom instructions updated",
            extra={"user_id": user.id, "has_instructions": bool(instructions)},
        )

    # WhatsApp phone: different PATCH semantics to allow clearing
    # - null → don't change (data.whatsapp_phone is None)
    # - "" → clear (data.whatsapp_phone is "")
    # - valid phone → update
    if "whatsapp_phone" in fields_set and data.whatsapp_phone is not None:
        # Empty string means clear, valid phone means update
        phone = data.whatsapp_phone if data.whatsapp_phone else None
        db.update_user_whatsapp_phone(user.id, phone)
        logger.info(
            "User WhatsApp phone updated",
            extra={"user_id": user.id, "has_phone": bool(phone)},
        )

    return {"status": "updated"}, 200
