"""Scheduled item routes: a chat's items, cancel, pause, resume.

Attached to conversations.api (items belong to chats). The Command Center's
"From chats" lane comes with its dashboard (agent_command_center.py).
"""

from src.api.errors import raise_conflict_error, raise_not_found_error
from src.api.helpers.schedule_responses import items_to_response
from src.api.routes.conversations import api
from src.api.schemas.schedules import ConversationSchedulesResponse, ScheduledItemResponse
from src.auth.jwt_auth import require_auth
from src.db.models import User, db

_ONE_OFFS = {"reminder", "check_in"}


@api.route("/conversations/<conv_id>/schedules", methods=["GET"])
@api.output(ConversationSchedulesResponse)
@api.doc(responses=[404])
@require_auth
def get_conversation_schedules(user: User, conv_id: str) -> tuple[dict[str, object], int]:
    """The chat's scheduled items, for its header chip."""
    if not db.get_conversation(conv_id, user.id):
        raise_not_found_error("Conversation")
    items = db.list_items(user.id, conversation_id=conv_id)
    return {"conversation_id": conv_id, "items": items_to_response(user.id, items)}, 200


@api.route("/schedules/<item_id>", methods=["DELETE"])
@api.doc(responses=[204, 404])
@require_auth
def delete_schedule(user: User, item_id: str) -> tuple[str, int]:
    """Cancel one of the user's scheduled items."""
    if not db.delete_item(item_id, user.id):
        raise_not_found_error("Scheduled item")
    return "", 204


def _set_paused(user: User, item_id: str, paused: bool) -> tuple[dict[str, object], int]:
    item = db.get_item(item_id, user.id)
    if item is None:
        raise_not_found_error("Scheduled item")
    if item.kind in _ONE_OFFS:
        raise_conflict_error("A reminder or check-in cannot be paused; cancel it instead.")
    if not db.set_item_paused(item_id, user.id, paused=paused):
        raise_conflict_error(
            "The item is running right now, or already in that state; try again shortly."
        )
    updated = db.get_item(item_id, user.id)
    if updated is None:
        raise_not_found_error("Scheduled item")
    return items_to_response(user.id, [updated])[0], 200


@api.route("/schedules/<item_id>/pause", methods=["POST"])
@api.output(ScheduledItemResponse)
@api.doc(responses=[404, 409])
@require_auth
def pause_schedule(user: User, item_id: str) -> tuple[dict[str, object], int]:
    """Pause a watcher or recurring check."""
    return _set_paused(user, item_id, paused=True)


@api.route("/schedules/<item_id>/resume", methods=["POST"])
@api.output(ScheduledItemResponse)
@api.doc(responses=[404, 409])
@require_auth
def resume_schedule(user: User, item_id: str) -> tuple[dict[str, object], int]:
    """Resume a paused watcher or recurring check (it runs on the next tick when due)."""
    return _set_paused(user, item_id, paused=False)
