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
