"""Third-party integration schemas: Todoist, Garmin, Rouvy, Google Calendar."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TodoistConnectRequest(BaseModel):
    """Schema for POST /auth/todoist/connect - Exchange OAuth code for token."""

    code: str = Field(..., min_length=1, description="OAuth authorization code from Todoist")
    state: str = Field(..., min_length=1, description="CSRF state token for validation")


class GarminConnectRequest(BaseModel):
    """Schema for POST /auth/garmin/connect - Login with email and password."""

    email: str = Field(..., min_length=1, description="Garmin Connect email address")
    password: str = Field(..., min_length=1, description="Garmin Connect password (never stored)")


class GarminMfaRequest(BaseModel):
    """Schema for POST /auth/garmin/mfa - Complete MFA login.

    The full login flow runs in a single backend request so no MFA session
    state needs to persist between requests (which would not survive gunicorn's
    multi-worker dispatch, since the garminconnect Client mid-MFA holds
    non-picklable curl_cffi sessions and thread locks).
    """

    email: str = Field(..., min_length=1, description="Garmin Connect email address")
    password: str = Field(..., min_length=1, description="Garmin Connect password (never stored)")
    mfa_code: str = Field(..., min_length=1, description="MFA verification code")


class RouvyConnectRequest(BaseModel):
    """Schema for POST /auth/rouvy/connect - headless login with email/password.

    Unlike Garmin, the password is stored (Fernet-encrypted) so the short-lived
    session cookie can be auto-refreshed via headless login.
    """

    email: str = Field(..., min_length=1, description="Rouvy account email")
    password: str = Field(
        ..., min_length=1, description="Rouvy account password (encrypted at rest)"
    )


class GoogleCalendarConnectRequest(BaseModel):
    """Schema for POST /auth/calendar/connect - Exchange OAuth code for token."""

    code: str = Field(..., min_length=1, description="OAuth authorization code from Google")
    state: str = Field(..., min_length=1, description="CSRF state token for validation")


class TodoistAuthUrlResponse(BaseModel):
    """Response containing Todoist OAuth authorization URL."""

    auth_url: str = Field(..., description="URL to redirect user for Todoist authorization")
    state: str = Field(..., description="CSRF state token to validate on callback")


class TodoistConnectResponse(BaseModel):
    """Response from successful Todoist connection."""

    connected: bool = Field(..., description="Whether connection was successful")
    todoist_email: str | None = Field(None, description="Email of connected Todoist account")


class TodoistStatusResponse(BaseModel):
    """Response containing Todoist connection status."""

    connected: bool = Field(..., description="Whether Todoist is connected")
    todoist_email: str | None = Field(None, description="Email of connected Todoist account")
    connected_at: str | None = Field(None, description="ISO timestamp when connected")
    needs_reconnect: bool = Field(
        False, description="True if token is invalid and user needs to reconnect"
    )


class GarminConnectResponse(BaseModel):
    """Response from Garmin Connect login attempt."""

    connected: bool = Field(..., description="Whether connection was successful")
    mfa_required: bool = Field(default=False, description="True if MFA verification is needed")
    display_name: str | None = Field(None, description="Display name of connected Garmin account")


class GarminStatusResponse(BaseModel):
    """Response containing Garmin connection status."""

    connected: bool = Field(..., description="Whether Garmin is connected")
    connected_at: str | None = Field(None, description="ISO timestamp when connected")
    needs_reconnect: bool = Field(
        False, description="True if session has expired and user must reconnect"
    )


class RouvyConnectResponse(BaseModel):
    """Response from a Rouvy connect attempt."""

    connected: bool = Field(..., description="Whether connection succeeded")


class RouvyStatusResponse(BaseModel):
    """Response containing Rouvy connection status."""

    connected: bool = Field(..., description="Whether Rouvy is connected")
    connected_at: str | None = Field(None, description="ISO timestamp when connected")
    needs_reconnect: bool = Field(False, description="True if the stored session looks unusable")


class GoogleCalendarAuthUrlResponse(BaseModel):
    """Response containing Google Calendar OAuth authorization URL."""

    auth_url: str = Field(..., description="URL to redirect user for Google authorization")
    state: str = Field(..., description="CSRF state token to validate on callback")


class GoogleCalendarConnectResponse(BaseModel):
    """Response from successful Google Calendar connection."""

    connected: bool = Field(..., description="Whether connection was successful")
    calendar_email: str | None = Field(
        None, description="Email of Google account granting Calendar access"
    )


class GoogleCalendarStatusResponse(BaseModel):
    """Response containing Google Calendar connection status."""

    connected: bool = Field(..., description="Whether Google Calendar is connected")
    calendar_email: str | None = Field(None, description="Email of connected Google account")
    connected_at: str | None = Field(None, description="ISO timestamp when connected")
    needs_reconnect: bool = Field(
        False, description="True if tokens are invalid/expired and user must reconnect"
    )


class Calendar(BaseModel):
    """A Google Calendar."""

    id: str = Field(..., description="Calendar ID")
    summary: str = Field(..., description="Calendar name/title")
    primary: bool = Field(..., description="Whether this is the user's primary calendar")
    access_role: str = Field(..., description="User's access level (owner, writer, reader)")
    background_color: str | None = Field(None, description="Calendar background color (hex)")


class CalendarListResponse(BaseModel):
    """Response for listing available calendars."""

    calendars: list[Calendar] = Field(
        default_factory=list, description="List of available calendars"
    )
    error: str | None = Field(None, description="Error message if fetch failed")


class SelectedCalendarsResponse(BaseModel):
    """Response for selected calendars."""

    calendar_ids: list[str] = Field(..., description="List of selected calendar IDs")


class UpdateSelectedCalendarsRequest(BaseModel):
    """Request to update selected calendars."""

    calendar_ids: list[str] = Field(..., description="List of calendar IDs to fetch events from")
