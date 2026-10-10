"""Chat request and message response schemas."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from src.api.schemas.files import (
    FileAttachment,
    FileMetadataResponse,
    GeneratedImageResponse,
    SourceResponse,
)
from src.config import Config


class ClientLocation(BaseModel):
    """Device GPS fix sent by the frontend when location sharing is enabled."""

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0)
    timestamp_ms: int | None = Field(default=None, ge=0)


class StopChatRequest(BaseModel):
    """Schema for POST /api/conversations/<conv_id>/chat/stop.

    Names the turn to stop by its assistant message id (from the stream's
    user_message_saved event), so a Stop never hits a different turn.
    """

    message_id: str = Field(..., min_length=1, max_length=64)


class InterjectRequest(BaseModel):
    """Schema for POST /api/conversations/<conv_id>/chat/interject.

    Mid-run steering: guidance for a turn that is currently streaming,
    injected between the agent's tool rounds.
    """

    message: str = Field(..., min_length=1, max_length=4000)
    client_message_id: str | None = Field(
        default=None, description="Id of the bubble the client rendered (saved under it; UUID)"
    )

    @field_validator("client_message_id")
    @classmethod
    def validate_client_message_id(cls, v: str | None) -> str | None:
        """Becomes the row's primary key - UUIDs only (as for chat sends)."""
        if v is not None and not re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", v
        ):
            raise ValueError("client_message_id must be a UUID")
        return v


class DeepResearchStart(BaseModel):
    """Start a deep-research run from an offer, with the user's final plan."""

    offer_message_id: str
    sub_questions: list[str] = Field(default_factory=list)
    context: str = ""


class VerifyClaimAction(BaseModel):
    """Look it up on a claim card: verify one claim of an earlier answer."""

    type: Literal["verify_claim"]
    source_message_id: str | None = None
    claim_index: int | None = Field(default=None, ge=0)
    quote: str = Field(..., max_length=500)


class DeepResearchAction(BaseModel):
    """Start on a deep-research offer (the server fills it from the started plan)."""

    type: Literal["deep_research"]
    offer_message_id: str
    items: int = Field(default=0, ge=0)
    minutes: int = Field(default=0, ge=0)


# What a user message sent on the user's behalf was (rendered as an action row)
MessageAction = Annotated[VerifyClaimAction | DeepResearchAction, Field(discriminator="type")]


class ResearchOfferUpdate(BaseModel):
    """The user's decision on an offer (starting goes through the chat stream)."""

    status: Literal["declined"]


class ChatRequest(BaseModel):
    """Schema for POST /api/conversations/<conv_id>/chat/batch and /chat/stream.

    Validates structure. File content validation happens separately via
    validate_files() in src/utils/files.py.
    """

    message: str = Field(default="")
    files: list[FileAttachment] = Field(default_factory=list)
    force_tools: list[str] = Field(default_factory=list)
    anonymous_mode: bool = Field(default=False)
    client_location: ClientLocation | None = Field(default=None)
    client_message_id: str | None = Field(default=None)
    # Re-run the agent on existing history without adding a user message:
    # "regenerate" (after the client deleted the last assistant message) or
    # "continue" (finish a truncated/stopped response)
    rerun_mode: Literal["regenerate", "continue"] | None = Field(default=None)
    deep_research: DeepResearchStart | None = Field(
        default=None, description="Run deep research from this offer (stream endpoint only)"
    )
    action: MessageAction | None = Field(
        default=None, description="What this message is, when the app sent it for the user"
    )

    @field_validator("client_message_id")
    @classmethod
    def validate_client_message_id(cls, v: str | None) -> str | None:
        """Client-generated message IDs become the row's primary key — UUIDs only."""
        if v is not None and not re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", v
        ):
            raise ValueError("client_message_id must be a UUID")
        return v

    @field_validator("force_tools")
    @classmethod
    def validate_force_tools(cls, v: list[str]) -> list[str]:
        """Restrict to plain tool identifiers.

        Items are interpolated verbatim into the LLM system prompt
        (get_force_tools_prompt), so anything beyond an identifier is a
        prompt-injection vector.
        """
        for name in v:
            if not re.fullmatch(r"[a-z0-9_]{1,64}", name):
                raise ValueError(f"Invalid tool name: {name!r}")
        return v

    @field_validator("files")
    @classmethod
    def validate_files_count(cls, v: list[FileAttachment]) -> list[FileAttachment]:
        """Validate file count limit."""
        if len(v) > Config.MAX_FILES_PER_MESSAGE:
            raise ValueError(f"Too many files. Maximum is {Config.MAX_FILES_PER_MESSAGE}")
        return v

    @model_validator(mode="after")
    def validate_message_or_files(self) -> ChatRequest:
        """Ensure at least message or files is provided (unless re-running)."""
        message_text = self.message.strip() if self.message else ""
        if self.rerun_mode:
            if message_text or self.files:
                raise ValueError("rerun_mode requests must not include message or files")
            return self
        if not message_text and not self.files:
            raise ValueError("Message or files required")
        return self


class ClaimAnnotationResponse(BaseModel):
    """A grounding-check claim in an assistant message."""

    type: Literal["claim"]
    verdict: Literal["supported", "partial", "not_found", "contradicted"]
    quote: str = Field(description="Literal phrase from the message content")
    prefix: str = Field(
        default="", description="Text right before the quote (disambiguates repeats)"
    )
    reason: str | None = None
    source: int | None = Field(default=None, description="1-based index into sources")
    source_quote: str | None = Field(default=None, description="Literal passage from that source")


class GroundingSummaryResponse(BaseModel):
    """Footer summary of a grounding-checked message."""

    checked: bool
    source_count: int | None = None
    legacy: bool | None = Field(
        default=None, description="Converted from pre-Oct-3-2026 inline markers"
    )


class MessageResponse(BaseModel):
    """Message in a conversation."""

    id: str
    role: Literal["user", "assistant"]
    content: str
    files: list[FileMetadataResponse] | None = None
    sources: list[SourceResponse] | None = None
    generated_images: list[GeneratedImageResponse] | None = None
    language: str | None = Field(
        default=None, description="ISO 639-1 language code for TTS (e.g., 'en', 'cs')"
    )
    stopped_early: bool | None = Field(
        default=None, description="Reply was cut off by the tool-round cap (offer Continue)"
    )
    stop_reason: Literal["user"] | None = Field(
        default=None,
        description="Why the reply ended early: 'user' = stopped by the user (offer Continue)",
    )
    annotations: list[ClaimAnnotationResponse] | None = None
    grounding: GroundingSummaryResponse | None = None
    research: dict[str, Any] | None = Field(
        default=None, description="Deep-research offer ({offer}) or run ({run}) data"
    )
    action: MessageAction | None = Field(
        default=None, description="What a message sent on the user's behalf was"
    )
    created_at: str


class ChatBatchResponse(BaseModel):
    """Response from batch chat endpoint."""

    id: str
    role: Literal["assistant"] = "assistant"
    content: str
    files: list[FileMetadataResponse] | None = None
    sources: list[SourceResponse] | None = None
    generated_images: list[GeneratedImageResponse] | None = None
    language: str | None = Field(
        default=None, description="ISO 639-1 language code for TTS (e.g., 'en', 'cs')"
    )
    stopped_early: bool | None = Field(
        default=None, description="Reply was cut off by the tool-round cap (offer Continue)"
    )
    stop_reason: Literal["user"] | None = Field(
        default=None,
        description="Why the reply ended early: 'user' = stopped by the user (offer Continue)",
    )
    annotations: list[ClaimAnnotationResponse] | None = None
    grounding: GroundingSummaryResponse | None = None
    research: dict[str, Any] | None = Field(
        default=None, description="Deep-research offer ({offer}) or run ({run}) data"
    )
    created_at: str
    title: str | None = Field(
        default=None, description="Auto-generated conversation title (first message only)"
    )
    user_message_id: str | None = Field(
        default=None, description="Real ID of the user message (for updating temp IDs in frontend)"
    )
    model_fallback: str | None = Field(
        default=None,
        description="Model that answered when the conversation's model was unavailable (503)",
    )
    message_count: int | None = Field(
        default=None,
        description="The conversation's message count after this turn (sync baseline)",
    )
