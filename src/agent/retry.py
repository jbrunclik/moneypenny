"""Retry logic for transient failures in agent execution.

Provides exponential backoff for handling transient failures like:
- Network timeouts
- API rate limits
- Temporary service unavailability
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

import httpx
import httpx2
from google.genai.errors import APIError as GenaiAPIError
from langchain_core.exceptions import ModelError

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


# Exceptions that should trigger a retry
TRANSIENT_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,  # Includes socket errors
    httpx.TransportError,  # network failures and timeouts (other clients)
    httpx2.TransportError,  # google-genai 3.x's: it sends through httpx2, not httpx
)

# google-genai API errors worth another attempt (langchain-google-genai 4.x
# also marks its own wrappers: ModelError.is_retryable)
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class PartialStreamError(Exception):
    """A model call failed after it had streamed text: never retried.

    A retry streamed the reply again while the failed attempt's text stayed
    on screen and in the saved reply, so it appeared twice (Nov 2026 audit).
    """


def _typed_verdict(error: BaseException) -> bool | None:
    """Whether this exception's own type says retry; None when it says nothing."""
    if isinstance(error, PartialStreamError):
        return False
    if isinstance(error, ModelError):
        return bool(error.is_retryable)
    if isinstance(error, GenaiAPIError):
        return error.code in _RETRYABLE_STATUS_CODES
    if isinstance(error, TRANSIENT_EXCEPTIONS):
        return True
    return None


# Patterns are only matched against the START of the message (see below):
# exception strings can embed tool/page payloads whose text ("timeout",
# "connection reset") is data, not an error condition.
_PATTERN_SCAN_CHARS = 300

# Error messages that indicate transient failures
TRANSIENT_ERROR_PATTERNS = (
    "rate limit",
    "quota exceeded",
    "temporarily unavailable",
    "service unavailable",
    "503",
    "429",
    "timeout",
    "connection reset",
    "connection refused",
)


def is_transient_error(error: Exception) -> bool:
    """Check if an error is transient and should be retried.

    Args:
        error: The exception to check

    Returns:
        True if the error is transient and retryable
    """
    # Walk the cause chain: provider SDKs wrap transient errors in their own
    # exception types (e.g. ChatGoogleGenerativeAIError around a 429). The
    # first type that classifies itself decides (a context overflow is not
    # retried whatever it wraps)
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        verdict = _typed_verdict(current)
        if verdict is not None:
            return verdict
        current = current.__cause__ or current.__context__

    # Pattern-match only the start of the message (payloads embedded in
    # exception strings must not false-positive)
    error_msg = str(error)[:_PATTERN_SCAN_CHARS].lower()
    return any(pattern in error_msg for pattern in TRANSIENT_ERROR_PATTERNS)


def is_model_unavailable(error: BaseException) -> bool:
    """Whether the model itself is down: 503 UNAVAILABLE ("high demand").

    Retrying such a model is futile for minutes at a time (Aug 27 2026: each
    retry spent ~40 s inside the SDK); the caller falls back to another model.
    Not after streamed text: the fallback's reply would follow it.
    """
    if isinstance(error, PartialStreamError):
        return False
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        head = str(current)[:_PATTERN_SCAN_CHARS].upper()
        if "503" in head and "UNAVAILABLE" in head:
            return True
        current = current.__cause__ or current.__context__
    return False


_TIMEOUT_EXCEPTIONS = (TimeoutError, httpx.TimeoutException, httpx2.TimeoutException)


def _is_unresponsive_link(error: BaseException) -> bool:
    """Whether this one exception says the model gave no answer in time."""
    if isinstance(error, _TIMEOUT_EXCEPTIONS):
        return True
    if isinstance(error, GenaiAPIError) and error.code == 504:
        return True
    head = str(error)[:_PATTERN_SCAN_CHARS].upper()
    return ("504" in head and "DEADLINE_EXCEEDED" in head) or "READ OPERATION TIMED OUT" in head


def is_model_unresponsive(error: BaseException) -> bool:
    """Whether the model is down or not answering: a 503, a 504 or a timeout.

    Nov 26 2026: Carbon answered every call for 20+ minutes with
    504 DEADLINE_EXCEEDED or nothing within the request timeout; three
    retries per call ran each turn into its stream limit with no reply.
    A turn with another tier to fall back to stops retrying on these.
    Not after streamed text: the fallback's reply would follow it.
    """
    if is_model_unavailable(error):
        return True
    if isinstance(error, PartialStreamError):
        return False
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, PartialStreamError):
            return False
        if _is_unresponsive_link(current):
            return True
        current = current.__cause__ or current.__context__
    return False


def fallback_reason(error: BaseException) -> str:
    """Why a turn fell back, for the log: unavailable (503), deadline (504) or timeout."""
    if is_model_unavailable(error):
        return "unavailable"
    head = str(error)[:_PATTERN_SCAN_CHARS].upper()
    return "deadline" if "504" in head or "DEADLINE" in head else "timeout"


def calculate_delay(attempt: int) -> float:
    """Calculate the delay before the next retry attempt.

    Uses exponential backoff with jitter to prevent thundering herd.

    Args:
        attempt: The attempt number (0-based)

    Returns:
        Delay in seconds
    """
    # Exponential backoff: base_delay * 2^attempt
    delay = Config.AGENT_RETRY_BASE_DELAY_SECONDS * (2**attempt)

    # Cap at max delay
    delay = min(delay, Config.AGENT_RETRY_MAX_DELAY_SECONDS)

    # Add jitter (±20%)
    jitter = delay * 0.2 * (random.random() * 2 - 1)  # noqa: S311 - jitter, not crypto
    delay += jitter

    return float(max(0.1, delay))  # Ensure minimum delay


def with_retry[T](
    func: Callable[..., T],
    max_retries: int | None = None,
    on_retry: Callable[[Exception, int], None] | None = None,
    give_up: Callable[[Exception], bool] = is_model_unavailable,
) -> Callable[..., T]:
    """Decorator to add retry logic with exponential backoff.

    Args:
        func: The function to wrap
        max_retries: Maximum number of retries (defaults to Config.AGENT_MAX_RETRIES)
        on_retry: Optional callback called before each retry with (error, attempt)
        give_up: Errors not worth retrying on this model (the caller falls
            back instead); a model that is down (503) by default

    Returns:
        Wrapped function with retry logic
    """
    if max_retries is None:
        max_retries = Config.AGENT_MAX_RETRIES

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e

                # Don't retry if not transient, the caller gives up on it, or last attempt
                if not is_transient_error(e) or give_up(e) or attempt >= max_retries:
                    raise

                # Calculate delay and sleep
                delay = calculate_delay(attempt)

                logger.warning(
                    "Transient error, retrying",
                    extra={
                        "error": str(e),
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                        "delay_seconds": delay,
                    },
                )

                if on_retry:
                    on_retry(e, attempt)

                time.sleep(delay)

        # Should never reach here, but satisfy type checker
        if last_error:
            raise last_error
        raise RuntimeError("Unexpected retry loop exit")

    return wrapper
