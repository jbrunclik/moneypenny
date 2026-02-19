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

from google.api_core.exceptions import (
    DeadlineExceeded,
    ResourceExhausted,
    ServiceUnavailable,
)

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


# Exceptions that should trigger a retry
TRANSIENT_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,  # Includes socket errors
    ResourceExhausted,  # Google API 429 rate limit
    ServiceUnavailable,  # Google API 503
    DeadlineExceeded,  # Google API 504
)

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
    # Check exception type
    if isinstance(error, TRANSIENT_EXCEPTIONS):
        return True

    # Check error message for patterns
    error_msg = str(error).lower()
    return any(pattern in error_msg for pattern in TRANSIENT_ERROR_PATTERNS)


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
    jitter = delay * 0.2 * (random.random() * 2 - 1)
    delay += jitter

    return float(max(0.1, delay))  # Ensure minimum delay


def with_retry[T](
    func: Callable[..., T],
    max_retries: int | None = None,
    on_retry: Callable[[Exception, int], None] | None = None,
) -> Callable[..., T]:
    """Decorator to add retry logic with exponential backoff.

    Args:
        func: The function to wrap
        max_retries: Maximum number of retries (defaults to Config.AGENT_MAX_RETRIES)
        on_retry: Optional callback called before each retry with (error, attempt)

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

                # Don't retry if not transient or last attempt
                if not is_transient_error(e) or attempt >= max_retries:
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


def retry_on_transient[T](
    max_retries: int | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator factory for retry_on_transient.

    Usage:
        @retry_on_transient()
        def my_function():
            ...

        @retry_on_transient(max_retries=5)
        def my_function():
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        return with_retry(func, max_retries=max_retries)

    return decorator
