"""Row -> dataclass converter shared by the message mixins."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from src.api.schemas.common import MessageRole
from src.db.models.dataclasses import Message


def row_to_message(row: sqlite3.Row) -> Message:
    """Convert a ``messages`` row to a Message object."""
    return Message(
        id=row["id"],
        conversation_id=row["conversation_id"],
        role=MessageRole(row["role"]),
        content=row["content"],
        created_at=datetime.fromisoformat(row["created_at"]),
        files=json.loads(row["files"]) if row["files"] else [],
        sources=json.loads(row["sources"]) if row["sources"] else None,
        tool_outputs=json.loads(row["tool_outputs"]) if row["tool_outputs"] else None,
        generated_images=json.loads(row["generated_images"]) if row["generated_images"] else None,
        language=row["language"],
        stop_reason=row["stop_reason"] if "stop_reason" in row.keys() else None,
        annotations=_json_column(row, "annotations"),
        grounding=_json_column(row, "grounding"),
    )


def _json_column(row: sqlite3.Row, name: str) -> Any:
    """Parsed JSON of an optional column (absent in rows selected without it)."""
    return json.loads(row[name]) if name in row.keys() and row[name] else None
