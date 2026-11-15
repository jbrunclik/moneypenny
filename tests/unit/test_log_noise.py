"""The ignored-`$defs` warning stays out of the log.

langchain-google-genai inlines a tool's `$ref`s and then logs "Key '$defs'
is not supported in schema, ignoring" for the leftover key (586 times in 30
days); the Nov 15 2026 audit read it as nested types being lost. They are
not (test_context_cache.py::TestNestedToolSchemas pins it), so the line goes.
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool
from langchain_google_genai._function_utils import convert_to_genai_function_declarations

import src.agent.tools as tools
from src.utils.logging import setup_logging


def _tool(name: str) -> BaseTool:
    return next(t for t in vars(tools).values() if isinstance(t, BaseTool) and t.name == name)


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def test_the_ignored_defs_warning_stays_out_of_the_log() -> None:
    setup_logging()
    records = _Records()
    logging.getLogger().addHandler(records)
    try:
        convert_to_genai_function_declarations([_tool("update_artifact")])
    finally:
        logging.getLogger().removeHandler(records)
    assert not [m for m in records.messages if "$defs" in m]
