"""Garmin Connect authentication via garminconnect library.

Uses garth for session management. The user's password is never stored —
only serialized garth session tokens (OAuth1 + OAuth2, valid ~1 year).

Token serialization uses garth's built-in Client.dumps()/loads() which
base64-encodes both OAuth1 and OAuth2 tokens together.

MFA handling does not carry partially-authenticated client state across HTTP
requests. The partially-authenticated client mid-MFA holds curl_cffi sessions
and thread locks that cannot be pickled (and therefore cannot cross gunicorn
workers). Instead, ``authenticate_with_mfa`` re-runs the full login in a
single request with ``prompt_mfa`` providing the code synchronously.
"""

from typing import Any, NoReturn

from src.utils.logging import get_logger

logger = get_logger(__name__)


class GarminAuthError(Exception):
    """Exception raised for Garmin authentication errors."""

    pass


class GarminMfaRequired(Exception):
    """Marker exception: caller should prompt the user for an MFA code and
    then call ``authenticate_with_mfa(email, password, mfa_code)``.

    Carries no client state — by design, so the MFA flow works across
    multiple gunicorn workers without needing cross-process state.
    """


def authenticate(email: str, password: str) -> tuple[str, str]:
    """Authenticate with Garmin Connect using email/password.

    Args:
        email: Garmin Connect email
        password: Garmin Connect password (used only for login, never stored)

    Returns:
        Tuple of (serialized_tokens_b64, display_name)

    Raises:
        GarminMfaRequired: If MFA is needed (caller should prompt for code,
            then call ``authenticate_with_mfa`` with the same credentials)
        GarminAuthError: If authentication fails
    """
    try:
        from garminconnect import Garmin

        garmin = Garmin(email=email, password=password, return_on_mfa=True)
        result = garmin.login()

        # With return_on_mfa=True, login returns:
        #   - Normal:    (OAuth1Token, OAuth2Token)
        #   - MFA needed: ("needs_mfa", None)
        if isinstance(result, tuple) and len(result) == 2 and result[0] == "needs_mfa":
            logger.info("Garmin MFA required", extra={"email": email})
            raise GarminMfaRequired()

        tokens = serialize_tokens(garmin)
        display_name = _get_display_name(garmin, email)

        logger.info("Garmin authentication successful", extra={"display_name": display_name})
        return tokens, display_name

    except GarminMfaRequired:
        raise
    except Exception as e:
        _raise_typed_error(e)


def authenticate_with_mfa(email: str, password: str, mfa_code: str) -> tuple[str, str]:
    """Authenticate by running the full login + MFA verification in one request.

    Re-initiates the Garmin login flow and supplies the MFA code via
    garminconnect's ``prompt_mfa`` callback. This avoids needing to retain a
    partially-authenticated Garmin client between HTTP requests (which would
    fail across gunicorn workers because the client is not picklable).

    Args:
        email: Garmin Connect email
        password: Garmin Connect password
        mfa_code: MFA verification code (OTP from email or authenticator app)

    Returns:
        Tuple of (serialized_tokens_b64, display_name)

    Raises:
        GarminAuthError: If the MFA code is wrong or the login otherwise fails
    """
    try:
        from garminconnect import Garmin

        # prompt_mfa is invoked synchronously by garminconnect when the MFA
        # step is reached; returning our code completes the flow inline.
        garmin = Garmin(email=email, password=password, prompt_mfa=lambda: mfa_code)
        garmin.login()

        tokens = serialize_tokens(garmin)
        display_name = _get_display_name(garmin, email)

        logger.info("Garmin MFA verification successful", extra={"display_name": display_name})
        return tokens, display_name

    except Exception as e:
        error_str = str(e).lower()
        if "mfa" in error_str or "verification" in error_str or "code" in error_str:
            raise GarminAuthError("Invalid MFA code. Please try again.") from e
        if "invalid" in error_str or "credentials" in error_str or "unauthorized" in error_str:
            raise GarminAuthError("Invalid email or password") from e
        if "rate" in error_str or "limit" in error_str or "too many" in error_str:
            raise GarminAuthError(
                "Rate limited by Garmin. Please try again in a few minutes."
            ) from e
        logger.error("Garmin MFA login failed", extra={"error": str(e)}, exc_info=True)
        raise GarminAuthError(f"MFA verification failed: {e}") from e


def serialize_tokens(garmin: Any) -> str:
    """Serialize garth session tokens using garth's built-in dumps().

    Args:
        garmin: Authenticated Garmin client

    Returns:
        Base64-encoded string containing both OAuth1 and OAuth2 tokens
    """
    try:
        return str(garmin.client.dumps())
    except Exception as e:
        logger.error("Failed to serialize Garmin tokens", extra={"error": str(e)})
        raise GarminAuthError("Failed to save session tokens") from e


def create_client_from_tokens(tokens_b64: str) -> Any:
    """Create an authenticated Garmin client from serialized tokens.

    Args:
        tokens_b64: Base64 token string from serialize_tokens()

    Returns:
        Authenticated Garmin client

    Raises:
        GarminAuthError: If tokens are invalid or expired
    """
    try:
        from garminconnect import Garmin

        # Use login(tokenstore=...) which loads tokens AND fetches the user
        # profile (display_name, full_name) — required for API URL construction.
        # Passing the base64 string directly works when len > 512.
        garmin = Garmin()
        garmin.login(tokenstore=tokens_b64)

        return garmin

    except Exception as e:
        error_str = str(e).lower()
        if "expired" in error_str or "unauthorized" in error_str or "401" in error_str:
            raise GarminAuthError("Session expired. Please reconnect your Garmin account.") from e
        if "assert" in error_str or "oauth1" in error_str:
            raise GarminAuthError("Session expired. Please reconnect your Garmin account.") from e
        logger.error(
            "Failed to create Garmin client from tokens", extra={"error": str(e)}, exc_info=True
        )
        raise GarminAuthError(f"Failed to restore session: {e}") from e


def refresh_and_serialize(garmin: Any) -> str:
    """Re-serialize tokens after API calls in case garth refreshed them.

    Args:
        garmin: Garmin client that may have refreshed tokens

    Returns:
        Updated base64 token string
    """
    return serialize_tokens(garmin)


def _get_display_name(garmin: Any, fallback: str) -> str:
    """Safely get the display name from a Garmin client."""
    try:
        name = getattr(garmin, "display_name", None) or garmin.get_full_name()
        return name or fallback
    except Exception:
        return fallback


def _raise_typed_error(e: Exception) -> NoReturn:
    """Classify a garminconnect exception and raise a typed GarminAuthError."""
    error_str = str(e).lower()

    if "invalid" in error_str or "credentials" in error_str or "unauthorized" in error_str:
        raise GarminAuthError("Invalid email or password") from e
    if "rate" in error_str or "limit" in error_str or "too many" in error_str:
        raise GarminAuthError("Rate limited. Please try again in a few minutes.") from e
    if "connection" in error_str or "timeout" in error_str or "network" in error_str:
        raise GarminAuthError("Cannot connect to Garmin. Please try again.") from e

    logger.error("Garmin authentication failed", extra={"error": str(e)}, exc_info=True)
    raise GarminAuthError(f"Authentication failed: {e}") from e
