"""What a lost turn already did (src/api/helpers/lost_actions.py).

The route-level behaviour (retry after a dead or failed turn) is in
tests/integration/test_routes_chat.py::TestLostTurnActions.
"""

import json
from unittest.mock import patch

from src.agent.tools import get_all_tool_names
from src.api.helpers import lost_actions


def test_side_effect_tools_exist() -> None:
    """A renamed tool would silently drop out of the note."""
    unknown = sorted(lost_actions.SIDE_EFFECT_TOOLS - get_all_tool_names())
    assert not unknown, f"side-effect tools that do not exist: {unknown}"


def test_calls_of_one_tool_end_in_order() -> None:
    events = [
        {"type": "tool_start", "tool": "todoist", "detail": "add_task: A"},
        {"type": "tool_start", "tool": "todoist", "detail": "add_task: B"},
        {"type": "tool_end", "tool": "todoist"},
    ]
    rows = [(i, json.dumps(e)) for i, e in enumerate(events, 1)]
    with patch.object(lost_actions.db, "journal_get_events", return_value=rows):
        actions = lost_actions._journal_actions("m1")
    assert actions[0] == "- todoist: add_task: A (finished)"
    assert actions[1].startswith("- todoist: add_task: B (cut off")
