"""Scheduled items set from chat: reminders, check-ins, watchers, recurring checks."""

from typing import Literal

from pydantic import Field

from src.api.schemas.base import ResponseModel, Timestamp

ItemKindField = Literal["reminder", "check_in", "watcher", "recurring"]


class ScheduledItemResponse(ResponseModel):
    """One item, described for people (household timezone)."""

    id: str
    conversation_id: str
    conversation_title: str = Field(description="Title of the chat the item belongs to")
    kind: ItemKindField
    title: str = Field(description="The item's text, shortened")
    when: str = Field(
        description="e.g. 'Fri 13 Nov 2026 18:00', 'checks daily', 'every Monday at 09:00'"
    )
    ends: str = Field(description="e.g. 'then done', 'until a job is posted, at most until 7 Dec'")
    status: Literal["active", "paused", "running"]
    next_run_at: Timestamp
    standing: bool = Field(
        default=False, description="A standing job (an agent's schedule): it can be run by hand"
    )
    paused_reason: str | None = Field(
        default=None, description="Why it is paused: 'failures' (kept failing), 'disabled'"
    )


class ConversationSchedulesResponse(ResponseModel):
    """A chat's items, for its header chip."""

    conversation_id: str
    items: list[ScheduledItemResponse]


class DeliveryResponse(ResponseModel):
    """The scheduled item that delivered an assistant turn."""

    kind: ItemKindField
    label: str = Field(description="e.g. 'Check-in · Fri 18:00', 'Watcher · found'")


class AgentDraftResponse(ResponseModel):
    """A chat's watcher or recurring check as a full agent, for the editor;
    creating it with replaces_item_id removes the item."""

    name: str
    instructions: str
    schedule: str | None = Field(description="Cron in `timezone`")
    timezone: str
    grants: list[str]
    fresh_context: bool
    replaces_item_id: str
