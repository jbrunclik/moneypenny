"""User settings schemas (including the daily briefing)."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


class UpdateDailyBriefingRequest(BaseModel):
    """Daily Briefing opt-in update (nested in UpdateSettingsRequest)."""

    enabled: bool
    time: str = Field(..., pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    timezone: str = Field(default="UTC", max_length=64)


class UpdateSettingsRequest(BaseModel):
    """Schema for PATCH /api/users/me/settings."""

    custom_instructions: str | None = Field(None, max_length=2000)
    daily_briefing: UpdateDailyBriefingRequest | None = None
    preferred_language: str | None = Field(
        None,
        max_length=32,
        description="Primary response language (English name); empty string = auto",
    )
    whatsapp_phone: str | None = Field(
        None,
        max_length=20,
        description="WhatsApp phone number in E.164 format (e.g., +1234567890). "
        "Must start with + followed by country code and at least 7 digits total. "
        "Send empty string to clear.",
    )

    @field_validator("whatsapp_phone")
    @classmethod
    def validate_whatsapp_phone(cls, v: str | None) -> str | None:
        """Validate WhatsApp phone number format.

        Returns:
            None if input is None (field not updated in PATCH)
            "" if input is empty string (clears the field)
            Validated phone number if valid E.164 format
        """

        if v is None:
            return None  # PATCH semantics: null means "don't change"
        if v.strip() == "":
            return ""  # Empty string means "clear this field"
        v = v.strip()
        # E.164 format: + followed by country code (1-3 digits) and subscriber number
        # Total length: 7-15 digits (including country code)
        if not re.match(r"^\+[1-9]\d{6,14}$", v):
            raise ValueError(
                "Invalid phone number format. Use E.164 format: +<country_code><number> "
                "(e.g., +1234567890). Must be 7-15 digits after the +."
            )
        return v


class DailyBriefingSettings(BaseModel):
    """Daily Briefing opt-in state (backed by a system-managed agent)."""

    enabled: bool = False
    time: str = Field(default="08:00", pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    timezone: str = Field(default="UTC", max_length=64)


class UserSettingsResponse(BaseModel):
    """User settings."""

    custom_instructions: str = Field(default="", description="Custom instructions for the AI")
    whatsapp_phone: str | None = Field(
        default=None, description="WhatsApp phone number in E.164 format"
    )
    whatsapp_available: bool = Field(
        default=False, description="Whether WhatsApp is configured at the app level"
    )
    preferred_language: str | None = Field(
        default=None,
        description="Primary response language (English name, e.g. 'Czech'); null = auto",
    )
    daily_briefing: DailyBriefingSettings = Field(default_factory=DailyBriefingSettings)
