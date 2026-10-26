"""Program schemas: shared quick actions, sports tracking, language learning."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from src.api.schemas.base import RequestModel, ResponseModel

QUICK_ACTIONS_MAX_PER_PROGRAM = 12


QUICK_ACTION_MAX_FIELDS = 6


class QuickActionItem(RequestModel):
    """A one-tap saved prompt for a program conversation."""

    id: str = Field(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    emoji: str = Field(..., min_length=1, max_length=10)
    label: str = Field(..., min_length=1, max_length=40)
    body: str = Field(..., min_length=1, max_length=2000)
    fields: list[str] = Field(default_factory=list, max_length=QUICK_ACTION_MAX_FIELDS)

    @field_validator("fields")
    @classmethod
    def _fields_non_empty_and_short(cls, value: list[str]) -> list[str]:
        cleaned = [f.strip() for f in value]
        if any(not f or len(f) > 40 for f in cleaned):
            raise ValueError("each field label must be 1-40 characters")
        return cleaned


class QuickActionResponse(ResponseModel):
    """A saved quick action as the program listings send it."""

    id: str
    emoji: str
    label: str
    body: str
    fields: list[str] = Field(default_factory=list)


class UpdateQuickActionsRequest(RequestModel):
    """Replace a program's full ordered quick-action list."""

    quick_actions: list[QuickActionItem] = Field(
        default_factory=list, max_length=QUICK_ACTIONS_MAX_PER_PROGRAM
    )


class SportsProgramItem(ResponseModel):
    """A single sports training program."""

    id: str
    name: str
    emoji: str
    created_at: str
    has_conversation: bool = False
    quick_actions: list[QuickActionResponse] = Field(default_factory=list)


class SportsProgramsResponse(ResponseModel):
    """List of user's sports programs."""

    programs: list[SportsProgramItem]


class CreateSportsProgramRequest(RequestModel):
    """Request to create a new sports program."""

    name: str = Field(..., min_length=1, max_length=100)
    emoji: str = Field(..., min_length=1, max_length=10)


class SportsConversationResponse(ResponseModel):
    """Sports program conversation with messages."""

    id: str
    title: str
    model: str
    program: str
    created_at: str
    updated_at: str
    messages: list[dict[str, Any]]


class SportsResetResponse(ResponseModel):
    """Response from resetting a sports conversation."""

    success: bool
    message: str


class LanguageProgramItem(ResponseModel):
    """A single language learning program."""

    id: str
    name: str
    emoji: str
    created_at: str
    has_conversation: bool = False
    quick_actions: list[QuickActionResponse] = Field(default_factory=list)


class LanguageProgramsResponse(ResponseModel):
    """List of user's language programs."""

    programs: list[LanguageProgramItem]


class CreateLanguageProgramRequest(RequestModel):
    """Request to create a new language program."""

    name: str = Field(..., min_length=1, max_length=100)
    emoji: str = Field(..., min_length=1, max_length=10)


class LanguageConversationResponse(ResponseModel):
    """Language program conversation with messages."""

    id: str
    title: str
    model: str
    program: str
    created_at: str
    updated_at: str
    messages: list[dict[str, Any]]


class LanguageResetResponse(ResponseModel):
    """Response from resetting a language conversation."""

    success: bool
    message: str
