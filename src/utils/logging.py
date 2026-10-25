"""Structured logging with JSON output for Loki compatibility.

This module provides structured logging that outputs JSON-formatted logs,
making it easy to integrate with Loki or other log aggregation systems.
All logs include a request_id field for correlation when available.
"""

import json
import logging
import sys
import traceback
from contextvars import ContextVar
from typing import Any, cast

from flask import g, has_request_context

from src.config import Config

# Context variable to store request ID per request
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Get the current request ID from context."""
    # Try Flask's g first (set by middleware)
    if has_request_context() and hasattr(g, "request_id"):
        return cast(str | None, g.request_id)
    # Fall back to context variable (for non-Flask contexts)
    return request_id_var.get()


def set_request_id(request_id: str) -> None:
    """Set the request ID in context."""
    request_id_var.set(request_id)
    if has_request_context():
        g.request_id = request_id


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        # Base log structure
        log_data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add request ID if available
        request_id = get_request_id()
        if request_id:
            log_data["request_id"] = request_id

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # Add extra fields from record
        # Standard logging uses __dict__ to store extra fields
        # Skip internal logging attributes
        skip_attrs = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "thread",
            "threadName",
            "exc_info",
            "exc_text",
            "stack_info",
            "taskName",
        }
        for key, value in record.__dict__.items():
            if key not in skip_attrs and not key.startswith("_"):
                log_data[key] = value  # noqa: PERF403

        # Also check for custom extra_fields attribute (from log_with_extra helper)
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)

        return json.dumps(log_data, default=str)


def setup_logging() -> None:
    """Configure structured logging for the application."""

    # Get log level from config (default to INFO)
    log_level_str = Config.LOG_LEVEL
    log_level = getattr(logging, log_level_str, logging.INFO)

    # Create JSON formatter
    formatter = JSONFormatter()

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers
    root_logger.handlers.clear()

    # Add console handler with JSON formatter
    # Use stderr for application logs (stdout is often captured by process managers)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Set levels for noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.WARNING)
    logging.getLogger("langgraph").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name."""
    return logging.getLogger(name)


def log_with_extra(
    logger: logging.Logger,
    level: int,
    message: str,
    **extra: Any,
) -> None:
    """Log a message with extra structured fields.

    Args:
        logger: The logger instance
        level: Log level (e.g., logging.INFO)
        message: The log message
        **extra: Additional fields to include in the log
    """
    # Create a new record with extra fields
    record = logging.LogRecord(
        name=logger.name,
        level=level,
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=None,
    )
    record.extra_fields = extra
    logger.handle(record)


def log_payload_snippet(
    logger: logging.Logger, payload: dict[str, Any], max_length: int = 500
) -> None:
    """Log a snippet of a payload for debugging.

    Args:
        logger: The logger instance
        payload: The payload to log
        max_length: Maximum length of the snippet
    """
    try:
        payload_str = json.dumps(payload, default=str)
        if len(payload_str) > max_length:  # noqa: SIM108
            snippet = payload_str[:max_length] + "..."
        else:
            snippet = payload_str
        logger.debug("Payload snippet", extra={"payload_snippet": snippet})
    except Exception:  # noqa: BLE001
        logger.debug("Failed to serialize payload for logging")
