"""The "Tool round completed" line counts an error the way the turn's
message_costs.tool_errors does (Nov 15 2026 audit: 78 turns had tool errors
while the log showed 7 - a tool's JSON error result has status "success")."""

from __future__ import annotations

import json
from unittest.mock import patch

from langchain_core.messages import ToolMessage

from src.agent import tool_node
from src.agent.tools.errors import tool_error


def _outcomes(messages: list[ToolMessage]) -> list[dict[str, object]]:
    with patch.object(tool_node.logger, "info") as info:
        tool_node._log_tool_round(messages, 12)
    [call] = [c for c in info.call_args_list if c.args[0] == "Tool round completed"]
    return list(call.kwargs["extra"]["outcomes"])


def test_a_json_error_result_is_an_error() -> None:
    failed = ToolMessage(
        content=tool_error("HTTP 403 when fetching x"), tool_call_id="1", name="fetch_url"
    )
    assert _outcomes([failed])[0]["status"] == "error"


def test_an_error_status_is_an_error() -> None:
    failed = ToolMessage(content="boom", tool_call_id="1", name="x", status="error")
    assert _outcomes([failed])[0]["status"] == "error"


def test_a_result_is_a_success() -> None:
    ok = ToolMessage(content=json.dumps({"success": True}), tool_call_id="1", name="x")
    assert _outcomes([ok])[0]["status"] == "success"
