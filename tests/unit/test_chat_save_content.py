"""The reply text save_message_to_db stores for files-only and stopped turns."""

from unittest.mock import MagicMock, patch

from src.agent.cancellation import STOPPED_EMPTY_TEXT
from src.api.helpers.chat_save import save_message_to_db
from src.config import Config


def _saved_content(content: str, files: list[dict], stop_reason: str | None) -> str:
    """Run the save with every collaborator faked; return the text it persisted."""
    module = "src.api.helpers.chat_save"
    with (
        patch(f"{module}.db") as mock_db,
        patch(f"{module}._extract_stream_metadata", return_value=([], [], "en")),
        patch(f"{module}._collect_generated_files", return_value=(files, [])),
        patch(f"{module}._research_for_turn", return_value=None),
        patch(f"{module}.resolve_title_update", return_value=None),
        patch(f"{module}.calculate_and_save_message_cost", return_value=0.0),
        patch(f"{module}.extract_artifact_refs", return_value=[]),
        patch(f"{module}.build_tool_outputs", return_value=None),
    ):
        mock_db.add_message.return_value = MagicMock(id="m1")
        result = save_message_to_db(
            content, [], [], {}, "c1", "u1", "model", "hi", "r1", True, stop_reason=stop_reason
        )
    assert result is not None
    return mock_db.add_message.call_args.args[2]


def test_files_only_turn_gets_the_default_text() -> None:
    saved = _saved_content("", [{"name": "a.png"}], None)
    assert saved == Config.DEFAULT_IMAGE_GENERATION_MESSAGE


def test_stopped_turn_without_text_gets_the_stop_placeholder() -> None:
    assert _saved_content("  ", [], "user") == STOPPED_EMPTY_TEXT


def test_text_is_saved_as_is() -> None:
    assert _saved_content("hello", [{"name": "a.png"}], "user") == "hello"
