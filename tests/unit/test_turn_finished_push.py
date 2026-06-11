"""Tests for turn-finished-while-backgrounded push notifications.

When an interactive chat turn completes but no client is connected
(mobile screen lock, app backgrounded -> proactive abort), the user gets
a web push pointing at the conversation. Covers the cleanup-thread save
path and the approval finalize path.
"""

from __future__ import annotations

import threading
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.api.helpers.chat_streaming import _finalize_approval_stream, cleanup_and_save


def _finished_thread() -> MagicMock:
    thread = MagicMock()
    thread.is_alive.return_value = False
    return thread


class TestCleanupThreadNotifies:
    def test_disconnected_save_sends_push(self) -> None:
        final_results = {
            "ready": True,
            "saved": False,
            "clean_content": "First line of the answer\nmore detail",
        }
        done_event = threading.Event()
        done_event.set()
        save_func = MagicMock()

        with patch("src.api.helpers.chat_streaming.send_push_to_user") as mock_push:
            cleanup_and_save(
                _finished_thread(),
                final_results,
                threading.Lock(),
                done_event,
                "conv-1",
                "user-1",
                save_func,
            )

        save_func.assert_called_once()
        mock_push.assert_called_once()
        args = mock_push.call_args
        assert args.args[0] == "user-1"
        assert args.args[1] == "Your answer is ready"
        assert args.args[2] == "First line of the answer"
        assert args.kwargs["url"] == "/#/conversations/conv-1"
        assert args.kwargs["tag"] == "turn-conv-1"

    def test_generator_already_saved_no_push(self) -> None:
        """Normal path: the generator saved and delivered - no nudge."""
        final_results = {"ready": True, "saved": True, "clean_content": "x"}
        done_event = threading.Event()
        done_event.set()
        save_func = MagicMock()

        with patch("src.api.helpers.chat_streaming.send_push_to_user") as mock_push:
            cleanup_and_save(
                _finished_thread(),
                final_results,
                threading.Lock(),
                done_event,
                "conv-1",
                "user-1",
                save_func,
            )

        save_func.assert_not_called()
        mock_push.assert_not_called()

    def test_not_ready_no_push(self) -> None:
        """Producer never finished (crash/timeout path) - no 'ready' nudge."""
        final_results = {"ready": False, "saved": False, "clean_content": ""}
        done_event = threading.Event()
        done_event.set()

        with patch("src.api.helpers.chat_streaming.send_push_to_user") as mock_push:
            cleanup_and_save(
                _finished_thread(),
                final_results,
                threading.Lock(),
                done_event,
                "conv-1",
                "user-1",
                MagicMock(),
            )

        mock_push.assert_not_called()


class TestApprovalFinalizeNotifies:
    def _context(self, client_connected: bool) -> SimpleNamespace:
        return SimpleNamespace(
            approval_info={
                "approval_id": "ap-1",
                "description": "send the email",
                "tool_name": "todoist",
                "sibling_results": [],
            },
            user_id="user-1",
            conv_id="conv-1",
            placeholder_saved=False,
            expected_assistant_msg_id="msg-1",
            final_results={"ready": True, "saved": False},
            client_connected=client_connected,
            user_msg=SimpleNamespace(id="user-msg-1"),
        )

    def test_disconnected_client_gets_approval_push(self) -> None:
        mock_db = MagicMock()
        with (
            patch("src.api.helpers.chat_streaming.db", mock_db),
            patch("src.api.helpers.chat_streaming.send_push_to_user") as mock_push,
        ):
            list(_finalize_approval_stream(self._context(client_connected=False)))

        mock_push.assert_called_once()
        args = mock_push.call_args
        assert args.args[1] == "Approval needed"
        assert args.args[2] == "send the email"
        assert args.kwargs["url"] == "/#/conversations/conv-1"
        assert args.kwargs["tag"] == "approval-ap-1"

    def test_connected_client_no_push(self) -> None:
        mock_db = MagicMock()
        message = MagicMock()
        message.id = "msg-1"
        message.created_at = datetime(2026, 6, 12, 10, 0, 0)
        mock_db.add_message.return_value = message
        with (
            patch("src.api.helpers.chat_streaming.db", mock_db),
            patch("src.api.helpers.chat_streaming.send_push_to_user") as mock_push,
        ):
            list(_finalize_approval_stream(self._context(client_connected=True)))

        mock_push.assert_not_called()
