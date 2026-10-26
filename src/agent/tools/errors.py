"""The one shape an agent tool reports a failure in (rule B5).

check_tool_results (src/agent/graph.py) recognises a failure as a JSON object
with an "error" key and guides the model to retry, unless the failure is marked
permanent with "retriable": false. A plain "Error: ..." string reads as a
success: no retry guidance, and the UI shows the call as fine.
"""

import json
from typing import Any


def tool_error(message: str, /, *, retriable: bool = True, **extra: Any) -> str:
    """A tool result reporting `message` as a failure.

    retriable=False for failures a retry cannot fix (the tool is unavailable
    here, an integration is not connected); extra fields ride along.
    """
    payload: dict[str, Any] = {"error": message, **extra}
    if not retriable:
        payload["retriable"] = False
    return json.dumps(payload, ensure_ascii=False)


def action_result(result: dict[str, Any]) -> str:
    """Serialize an action handler's result; one with an "error" goes out as tool_error().

    For dispatchers whose handlers return dicts: the error text and the other
    fields ride along unchanged, a non-text error (a Todoist sync status) as
    its JSON.
    """
    if not result.get("error"):
        return json.dumps(result)
    extra = dict(result)
    error = extra.pop("error")
    retriable = bool(extra.pop("retriable", True))
    message = error if isinstance(error, str) else json.dumps(error, ensure_ascii=False)
    return tool_error(message, retriable=retriable, **extra)
