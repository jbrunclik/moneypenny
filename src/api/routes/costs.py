"""Cost tracking routes: conversation, message, monthly, and history costs.

This module handles cost tracking and reporting for API usage.
"""

from datetime import datetime
from typing import Any

from apiflask import APIBlueprint
from flask import request

from src.api.errors import raise_not_found_error, raise_validation_error
from src.api.schemas import (
    ConversationCostResponse,
    CostHistoryResponse,
    MessageCostResponse,
    MonthlyCostResponse,
)
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User, db
from src.utils.costs import convert_currency, format_cost
from src.utils.logging import get_logger

logger = get_logger(__name__)

api = APIBlueprint("costs", __name__, url_prefix="/api", tag="Costs")


# ============================================================================
# Cost Tracking Routes
# ============================================================================


@api.route("/conversations/<conv_id>/cost", methods=["GET"])
@api.output(ConversationCostResponse)
@api.doc(responses=[404])
@require_auth
def get_conversation_cost(user: User, conv_id: str) -> tuple[dict[str, Any], int]:
    """Get total cost for a conversation."""
    logger.debug(
        "Getting conversation cost", extra={"user_id": user.id, "conversation_id": conv_id}
    )

    # Verify conversation belongs to user
    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        logger.warning(
            "Conversation not found for cost query",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")

    cost_usd = db.get_conversation_cost(conv_id)
    cost_display = convert_currency(cost_usd, Config.COST_CURRENCY)
    formatted_cost = format_cost(cost_display, Config.COST_CURRENCY)

    logger.info(
        "Conversation cost retrieved",
        extra={"user_id": user.id, "conversation_id": conv_id, "cost_usd": cost_usd},
    )

    return {
        "conversation_id": conv_id,
        "cost_usd": cost_usd,
        "cost": cost_display,
        "currency": Config.COST_CURRENCY,
        "formatted": formatted_cost,
    }, 200


@api.route("/messages/<message_id>/cost", methods=["GET"])
@api.output(MessageCostResponse)
@api.doc(responses=[404])
@require_auth
def get_message_cost(user: User, message_id: str) -> tuple[dict[str, Any], int]:
    """Get cost for a specific message."""
    logger.debug("Getting message cost", extra={"user_id": user.id, "message_id": message_id})

    # Verify message belongs to user
    message = db.get_message_by_id(message_id)
    if not message:
        logger.warning(
            "Message not found for cost query",
            extra={"user_id": user.id, "message_id": message_id},
        )
        raise_not_found_error("Message")

    conv = db.get_conversation(message.conversation_id, user.id)
    if not conv:
        logger.warning(
            "Conversation not found for message cost query",
            extra={
                "user_id": user.id,
                "message_id": message_id,
                "conversation_id": message.conversation_id,
            },
        )
        raise_not_found_error("Message")

    cost_data = db.get_message_cost(message_id)
    if not cost_data:
        logger.debug(
            "No cost data found for message",
            extra={"user_id": user.id, "message_id": message_id},
        )
        raise_not_found_error("Cost data for this message")

    cost_display = convert_currency(cost_data["cost_usd"], Config.COST_CURRENCY)
    formatted_cost = format_cost(cost_display, Config.COST_CURRENCY)

    image_gen_cost_usd = cost_data.get("image_generation_cost_usd", 0.0)
    image_gen_cost_display = convert_currency(image_gen_cost_usd, Config.COST_CURRENCY)
    image_gen_cost_formatted = (
        format_cost(image_gen_cost_display, Config.COST_CURRENCY)
        if image_gen_cost_usd > 0
        else None
    )

    logger.info(
        "Message cost retrieved",
        extra={
            "user_id": user.id,
            "message_id": message_id,
            "cost_usd": cost_data["cost_usd"],
            "image_generation_cost_usd": image_gen_cost_usd,
        },
    )

    response = {
        "message_id": message_id,
        "cost_usd": cost_data["cost_usd"],
        "cost": cost_display,
        "currency": Config.COST_CURRENCY,
        "formatted": formatted_cost,
        "input_tokens": cost_data["input_tokens"],
        "output_tokens": cost_data["output_tokens"],
        "model": cost_data["model"],
    }

    if image_gen_cost_usd > 0:
        response["image_generation_cost_usd"] = image_gen_cost_usd
        response["image_generation_cost"] = image_gen_cost_display
        response["image_generation_cost_formatted"] = image_gen_cost_formatted

    return response, 200


@api.route("/users/me/costs/monthly", methods=["GET"])
@api.output(MonthlyCostResponse)
@api.doc(responses=[400])
@require_auth
def get_user_monthly_cost(user: User) -> tuple[dict[str, Any], int]:
    """Get cost for the current user in a specific month."""
    # Get year and month from query params (default to current month)
    now = datetime.now()
    year = request.args.get("year", type=int) or now.year
    month = request.args.get("month", type=int) or now.month

    # Validate month range
    if not (1 <= month <= 12):
        logger.warning(
            "Invalid month in request",
            extra={"user_id": user.id, "year": year, "month": month},
        )
        raise_validation_error("Month must be between 1 and 12", field="month")

    logger.debug(
        "Getting user monthly cost",
        extra={"user_id": user.id, "year": year, "month": month},
    )

    cost_data = db.get_user_monthly_cost(user.id, year, month)
    cost_display = convert_currency(cost_data["total_usd"], Config.COST_CURRENCY)
    formatted_cost = format_cost(cost_display, Config.COST_CURRENCY)

    # Convert breakdown to display currency
    breakdown_display = {}
    for model, data in cost_data["breakdown"].items():
        breakdown_display[model] = {
            "total": convert_currency(data["total_usd"], Config.COST_CURRENCY),
            "total_usd": data["total_usd"],
            "message_count": data["message_count"],
            "formatted": format_cost(
                convert_currency(data["total_usd"], Config.COST_CURRENCY), Config.COST_CURRENCY
            ),
        }

    logger.info(
        "User monthly cost retrieved",
        extra={
            "user_id": user.id,
            "year": year,
            "month": month,
            "total_usd": cost_data["total_usd"],
            "message_count": cost_data["message_count"],
        },
    )

    return {
        "user_id": user.id,
        "year": year,
        "month": month,
        "total_usd": cost_data["total_usd"],
        "total": cost_display,
        "currency": Config.COST_CURRENCY,
        "formatted": formatted_cost,
        "message_count": cost_data["message_count"],
        "breakdown": breakdown_display,
    }, 200


@api.route("/users/me/costs/history", methods=["GET"])
@api.output(CostHistoryResponse)
@require_auth
def get_user_cost_history(user: User) -> tuple[dict[str, Any], int]:
    """Get monthly cost history for the current user."""
    limit = request.args.get("limit", type=int) or Config.COST_HISTORY_DEFAULT_LIMIT
    # Cap limit to prevent performance issues
    limit = min(limit, Config.COST_HISTORY_MAX_MONTHS)
    logger.debug("Getting user cost history", extra={"user_id": user.id, "limit": limit})

    history = db.get_user_cost_history(user.id, limit)

    # Get current month
    now = datetime.now()
    current_year = now.year
    current_month = now.month

    # Convert each month's cost to display currency
    history_display = []
    current_month_in_history = False
    for month_data in history:
        year = month_data["year"]
        month = month_data["month"]

        # Check if this is the current month
        if year == current_year and month == current_month:
            current_month_in_history = True

        cost_display = convert_currency(month_data["total_usd"], Config.COST_CURRENCY)
        history_display.append(
            {
                "year": year,
                "month": month,
                "total_usd": month_data["total_usd"],
                "total": cost_display,
                "currency": Config.COST_CURRENCY,
                "formatted": format_cost(cost_display, Config.COST_CURRENCY),
                "message_count": month_data["message_count"],
            }
        )

    # If current month is not in history, add it with $0 cost
    if not current_month_in_history:
        history_display.insert(
            0,
            {
                "year": current_year,
                "month": current_month,
                "total_usd": 0.0,
                "total": 0.0,
                "currency": Config.COST_CURRENCY,
                "formatted": format_cost(0.0, Config.COST_CURRENCY),
                "message_count": 0,
            },
        )

    logger.info(
        "User cost history retrieved",
        extra={"user_id": user.id, "months_count": len(history_display)},
    )

    return {
        "user_id": user.id,
        "history": history_display,
    }, 200
