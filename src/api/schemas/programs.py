"""Program schemas: shared quick actions, sports tracking, language learning."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

QUICK_ACTIONS_MAX_PER_PROGRAM = 12


QUICK_ACTION_MAX_FIELDS = 6


class QuickActionItem(BaseModel):
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


class UpdateQuickActionsRequest(BaseModel):
    """Replace a program's full ordered quick-action list."""

    quick_actions: list[QuickActionItem] = Field(
        default_factory=list, max_length=QUICK_ACTIONS_MAX_PER_PROGRAM
    )


class SportsProgramItem(BaseModel):
    """A single sports training program."""

    id: str
    name: str
    emoji: str
    created_at: str
    has_conversation: bool = False
    quick_actions: list[QuickActionItem] = Field(default_factory=list)


class SportsProgramsResponse(BaseModel):
    """List of user's sports programs."""

    programs: list[SportsProgramItem]


class CreateSportsProgramRequest(BaseModel):
    """Request to create a new sports program."""

    name: str = Field(..., min_length=1, max_length=100)
    emoji: str = Field(..., min_length=1, max_length=10)


class SportsConversationResponse(BaseModel):
    """Sports program conversation with messages."""

    id: str
    title: str
    model: str
    program: str
    created_at: str
    updated_at: str
    messages: list[dict[str, Any]]


class SportsResetResponse(BaseModel):
    """Response from resetting a sports conversation."""

    success: bool
    message: str


class LanguageProgramItem(BaseModel):
    """A single language learning program."""

    id: str
    name: str
    emoji: str
    created_at: str
    has_conversation: bool = False
    quick_actions: list[QuickActionItem] = Field(default_factory=list)


class LanguageProgramsResponse(BaseModel):
    """List of user's language programs."""

    programs: list[LanguageProgramItem]


class CreateLanguageProgramRequest(BaseModel):
    """Request to create a new language program."""

    name: str = Field(..., min_length=1, max_length=100)
    emoji: str = Field(..., min_length=1, max_length=10)


class LanguageConversationResponse(BaseModel):
    """Language program conversation with messages."""

    id: str
    title: str
    model: str
    program: str
    created_at: str
    updated_at: str
    messages: list[dict[str, Any]]


class LanguageResetResponse(BaseModel):
    """Response from resetting a language conversation."""

    success: bool
    message: str
