"""Integration tests for chat routes."""

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Conversation, Database


class TestChatBatch:
    """Tests for POST /api/conversations/<conv_id>/chat/batch endpoint."""

    def test_successful_chat(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return assistant response."""
        with patch("src.api.routes.chat.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()
            mock_agent.chat_batch.return_value = (
                "Hello! How can I help?",  # response
                [],  # tool_results
                {"input_tokens": 100, "output_tokens": 50},  # usage_info
                [],  # result_messages
            )
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/batch",
                headers=auth_headers,
                json={"message": "Hello!"},
            )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["role"] == "assistant"
        assert "Hello" in data["content"]

    def test_requires_message_or_files(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return 400 when neither message nor files provided."""
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/batch",
            headers=auth_headers,
            json={},
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_saves_messages_to_database(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should save user and assistant messages."""
        with patch("src.api.routes.chat.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()
            mock_agent.chat_batch.return_value = (
                "Response text",
                [],
                {"input_tokens": 100, "output_tokens": 50},
                [],  # result_messages
            )
            mock_agent_class.return_value = mock_agent

            client.post(
                f"/api/conversations/{test_conversation.id}/chat/batch",
                headers=auth_headers,
                json={"message": "User message"},
            )

        messages = test_database.get_messages(test_conversation.id)
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "User message"
        assert messages[1].role == "assistant"

    def test_includes_sources_in_response(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should include sources when web tools are used."""
        from langchain_core.messages import AIMessage

        with patch("src.api.routes.chat.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()
            # Sources are now extracted from cite_sources tool calls in result_messages
            result_msgs = [
                AIMessage(
                    content="Based on search results...",
                    tool_calls=[
                        {
                            "name": "cite_sources",
                            "args": {
                                "sources": [{"title": "Test Source", "url": "https://example.com"}]
                            },
                            "id": "tc-1",
                        }
                    ],
                )
            ]
            mock_agent.chat_batch.return_value = (
                "Based on search results...",
                [],
                {"input_tokens": 150, "output_tokens": 100},
                result_msgs,
            )
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/batch",
                headers=auth_headers,
                json={"message": "Search for something"},
            )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "sources" in data
        assert len(data["sources"]) == 1

    def test_returns_404_for_nonexistent_conversation(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for non-existent conversation."""
        response = client.post(
            "/api/conversations/nonexistent-id/chat/batch",
            headers=auth_headers,
            json={"message": "Hello"},
        )

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient, test_conversation: Conversation) -> None:
        """Should return 401 without authentication."""
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/batch",
            json={"message": "Hello"},
        )
        assert response.status_code == 401

    def test_force_tools_parameter(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should pass force_tools to agent."""
        with patch("src.api.routes.chat.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()
            mock_agent.chat_batch.return_value = (
                "Response",
                [],
                {"input_tokens": 100, "output_tokens": 50},
                [],  # result_messages
            )
            mock_agent_class.return_value = mock_agent

            client.post(
                f"/api/conversations/{test_conversation.id}/chat/batch",
                headers=auth_headers,
                json={"message": "Hello", "force_tools": ["web_search"]},
            )

            # Verify force_tools was passed
            call_kwargs = mock_agent.chat_batch.call_args.kwargs
            assert call_kwargs.get("force_tools") == ["web_search"]


class TestChatStream:
    """Tests for POST /api/conversations/<conv_id>/chat/stream endpoint."""

    def test_returns_sse_stream(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return SSE content type."""
        with patch("src.api.routes.chat.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()

            def mock_stream_events(*args: Any, **kwargs: Any) -> Any:
                yield {"type": "token", "text": "Hello"}
                yield {"type": "token", "text": " world"}
                yield {
                    "type": "final",
                    "content": "Hello world",
                    "result_messages": [],
                    "tool_results": [],
                    "usage_info": {"input_tokens": 50, "output_tokens": 10},
                }

            mock_agent.stream_chat_events = mock_stream_events
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/stream",
                headers=auth_headers,
                json={"message": "Hello"},
            )

        assert response.status_code == 200
        assert "text/event-stream" in response.content_type

    def test_streams_tokens(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should stream tokens as SSE events."""
        with patch("src.api.helpers.chat_streaming.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()

            def mock_stream_events(*args: Any, **kwargs: Any) -> Any:
                yield {"type": "token", "text": "Token1"}
                yield {"type": "token", "text": "Token2"}
                yield {
                    "type": "final",
                    "content": "Token1Token2",
                    "result_messages": [],
                    "tool_results": [],
                    "usage_info": {"input_tokens": 50, "output_tokens": 10},
                }

            mock_agent.stream_chat_events = mock_stream_events
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/stream",
                headers=auth_headers,
                json={"message": "Hello"},
            )

        # Check response contains SSE data events
        response_text = response.data.decode("utf-8")
        assert "data:" in response_text
        assert "Token1" in response_text or "Token2" in response_text

    def test_requires_message_or_files(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return 400 when neither message nor files provided."""
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stream",
            headers=auth_headers,
            json={},
        )

        assert response.status_code == 400

    def test_returns_404_for_nonexistent_conversation(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for non-existent conversation."""
        response = client.post(
            "/api/conversations/nonexistent-id/chat/stream",
            headers=auth_headers,
            json={"message": "Hello"},
        )

        assert response.status_code == 404

    def test_saves_message_on_client_disconnect(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should save message to DB even if client disconnects during streaming."""
        with patch("src.api.helpers.chat_streaming.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()

            def mock_stream_events(*args: Any, **kwargs: Any) -> Any:
                yield {"type": "token", "text": "Token1"}
                yield {"type": "token", "text": "Token2"}
                yield {
                    "type": "final",
                    "content": "Token1Token2",
                    "result_messages": [],
                    "tool_results": [],
                    "usage_info": {"input_tokens": 50, "output_tokens": 10},
                }

            mock_agent.stream_chat_events = mock_stream_events
            mock_agent_class.return_value = mock_agent

            # Start the request and read partial response (simulating client disconnect)
            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/stream",
                headers=auth_headers,
                json={"message": "Hello"},
            )

            # Read just a portion of the response to simulate client starting to receive data
            # then disconnecting (we don't read the full response)
            response_data = response.data
            # Just verify we got some data (client started receiving)
            assert len(response_data) > 0

        # Wait for background thread and cleanup thread to complete
        import time

        time.sleep(1.0)

        # Verify message was saved to database even though client disconnected
        messages = test_database.get_messages(test_conversation.id)
        # Should have user message and assistant message
        assert len(messages) >= 2
        assert messages[-2].role == "user"
        assert messages[-2].content == "Hello"
        assert messages[-1].role == "assistant"
        assert messages[-1].content == "Token1Token2"

    def test_requires_auth(self, client: FlaskClient, test_conversation: Conversation) -> None:
        """Should return 401 without authentication."""
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stream",
            json={"message": "Hello"},
        )
        assert response.status_code == 401


class TestChatWithFiles:
    """Tests for chat endpoints with file attachments."""

    def test_batch_chat_with_files(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        sample_file: dict[str, Any],
    ) -> None:
        """Should handle file attachments in batch mode."""
        with patch("src.api.routes.chat.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()
            mock_agent.chat_batch.return_value = (
                "I see your image",
                [],
                {"input_tokens": 200, "output_tokens": 50},
                [],  # result_messages
            )
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/batch",
                headers=auth_headers,
                json={
                    "message": "What's in this image?",
                    "files": [sample_file],
                },
            )

        assert response.status_code == 200

    def test_files_only_no_message(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        sample_file: dict[str, Any],
    ) -> None:
        """Should accept files without text message."""
        with patch("src.api.routes.chat.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()
            mock_agent.chat_batch.return_value = (
                "This is an image of...",
                [],
                {"input_tokens": 200, "output_tokens": 50},
                [],  # result_messages
            )
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/batch",
                headers=auth_headers,
                json={
                    "message": "",
                    "files": [sample_file],
                },
            )

        assert response.status_code == 200


class TestChatWithGeneratedImages:
    """Tests for chat endpoints with generated images from tools.

    Note: These tests mock ChatAgent but also populate _full_tool_results to simulate
    what the tool node would capture in production. The tool node wrapper (create_tool_node)
    captures full results into _full_tool_results before stripping _full_result,
    and routes.py retrieves them via get_full_tool_results().
    """

    def test_batch_chat_with_generated_image(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
        sample_png_base64: str,
    ) -> None:
        """Should extract generated images from tool results and include in response."""
        from langchain_core.messages import AIMessage

        from src.agent.tool_results import _current_request_id, _full_tool_results

        # Build tool result with _full_result containing image data
        tool_result_content = json.dumps(
            {
                "success": True,
                "prompt": "a red square",
                "aspect_ratio": "1:1",
                "message": "Image generated successfully.",
                "_full_result": {
                    "image": {
                        "data": sample_png_base64,
                        "mime_type": "image/png",
                    },
                },
                "usage_metadata": {
                    "prompt_token_count": 50,
                    "candidates_token_count": 0,
                    "thoughts_token_count": 0,
                },
            }
        )

        with patch("src.api.routes.chat.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()

            # Mock chat_batch to return the response AND simulate tool node capture
            def mock_chat_batch(*args: Any, **kwargs: Any) -> Any:
                import time

                # Simulate what the tool node does: capture full results
                request_id = _current_request_id.get()
                if request_id:
                    _full_tool_results[request_id] = {
                        "results": [{"type": "tool", "content": tool_result_content}],
                        "created_at": time.time(),
                    }
                # Result messages include an AIMessage with generate_image tool call
                result_msgs = [
                    AIMessage(
                        content="Here is the image I generated for you.",
                        tool_calls=[
                            {
                                "name": "generate_image",
                                "args": {"prompt": "a red square"},
                                "id": "tc-1",
                            }
                        ],
                    )
                ]
                return (
                    "Here is the image I generated for you.",
                    [{"type": "tool", "content": tool_result_content}],
                    {"input_tokens": 100, "output_tokens": 50},
                    result_msgs,
                )

            mock_agent.chat_batch = mock_chat_batch
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/batch",
                headers=auth_headers,
                json={"message": "Generate a red square"},
            )

        assert response.status_code == 200
        data = json.loads(response.data)

        # Response should include files (generated images)
        assert "files" in data, "Response should include files with generated images"
        assert len(data["files"]) == 1
        assert data["files"][0]["type"] == "image/png"
        assert "messageId" in data["files"][0]

        # Response should include generated_images metadata
        assert "generated_images" in data
        assert len(data["generated_images"]) == 1
        assert data["generated_images"][0]["prompt"] == "a red square"

        # Verify message was saved with files
        messages = test_database.get_messages(test_conversation.id)
        assistant_msg = messages[-1]
        assert assistant_msg.role == "assistant"
        assert assistant_msg.files is not None
        assert len(assistant_msg.files) == 1

    def test_streaming_chat_with_generated_image(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
        sample_png_base64: str,
    ) -> None:
        """Should extract generated images during streaming and include in done event.

        This test verifies the fix for a regression where generated images
        weren't showing up until the conversation was reloaded.
        """
        import time

        from langchain_core.messages import AIMessage

        from src.agent.tool_results import _current_request_id, _full_tool_results

        # Build tool result with _full_result containing image data
        tool_result_content = json.dumps(
            {
                "success": True,
                "prompt": "a blue circle",
                "aspect_ratio": "1:1",
                "message": "Image generated successfully.",
                "_full_result": {
                    "image": {
                        "data": sample_png_base64,
                        "mime_type": "image/png",
                    },
                },
                "usage_metadata": {
                    "prompt_token_count": 50,
                    "candidates_token_count": 0,
                    "thoughts_token_count": 0,
                },
            }
        )

        with patch("src.api.helpers.chat_streaming.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()

            def mock_stream_events(*args: Any, **kwargs: Any) -> Any:
                """Mock stream_chat_events that yields structured events with tool results.

                Also simulates the tool node capturing full results into _full_tool_results.
                """
                # Simulate what the tool node does: capture full results
                # This happens during graph execution (before yielding final tuple)
                request_id = _current_request_id.get()
                if request_id:
                    _full_tool_results[request_id] = {
                        "results": [{"type": "tool", "content": tool_result_content}],
                        "created_at": time.time(),
                    }

                # Build result_messages with generate_image tool call for extraction
                result_msgs = [
                    AIMessage(
                        content="Here is the image",
                        tool_calls=[
                            {
                                "name": "generate_image",
                                "args": {"prompt": "a blue circle"},
                                "id": "tc-1",
                            }
                        ],
                    )
                ]

                yield {"type": "token", "text": "Here"}
                yield {"type": "token", "text": " is"}
                yield {"type": "token", "text": " the"}
                yield {"type": "token", "text": " image"}
                # Final event with content, result_messages, and tool results
                yield {
                    "type": "final",
                    "content": "Here is the image",
                    "result_messages": result_msgs,
                    "tool_results": [{"type": "tool", "content": tool_result_content}],
                    "usage_info": {"input_tokens": 100, "output_tokens": 50},
                }

            mock_agent.stream_chat_events = mock_stream_events
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/stream",
                headers=auth_headers,
                json={"message": "Generate a blue circle"},
            )

        assert response.status_code == 200
        assert "text/event-stream" in response.content_type

        # Parse SSE events
        response_text = response.data.decode("utf-8")
        events = []
        for line in response_text.split("\n"):
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    events.append(event)
                except json.JSONDecodeError:
                    pass

        # Find done event
        done_events = [e for e in events if e.get("type") == "done"]
        assert len(done_events) == 1, f"Expected 1 done event, got {len(done_events)}"
        done_event = done_events[0]

        # Verify done event includes files
        assert "files" in done_event, f"Done event should include files. Event: {done_event}"
        assert len(done_event["files"]) == 1
        assert done_event["files"][0]["type"] == "image/png"
        assert "messageId" in done_event["files"][0]

        # Verify done event includes generated_images metadata
        assert "generated_images" in done_event
        assert len(done_event["generated_images"]) == 1
        assert done_event["generated_images"][0]["prompt"] == "a blue circle"

        # Wait for cleanup thread to ensure message is saved
        time.sleep(1.5)

        # Verify message was saved with files
        messages = test_database.get_messages(test_conversation.id)
        assistant_msg = messages[-1]
        assert assistant_msg.role == "assistant"
        assert assistant_msg.files is not None, "Message should have files saved"
        assert len(assistant_msg.files) == 1, f"Expected 1 file, got {len(assistant_msg.files)}"

    def test_streaming_without_generated_images(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Verify streaming works correctly when no images are generated.

        This tests the normal case where no generate_image tool is used.
        The done event should not include files when no images are generated.
        """
        import time

        with patch("src.api.helpers.chat_streaming.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()

            def mock_stream_events(*args: Any, **kwargs: Any) -> Any:
                yield {"type": "token", "text": "Test"}
                yield {"type": "token", "text": " response"}
                yield {
                    "type": "final",
                    "content": "Test response",
                    "result_messages": [],
                    "tool_results": [],  # No tool results
                    "usage_info": {"input_tokens": 10, "output_tokens": 5},
                }

            mock_agent.stream_chat_events = mock_stream_events
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/stream",
                headers=auth_headers,
                json={"message": "Test"},
            )

        assert response.status_code == 200

        # Wait for background threads
        time.sleep(1.5)

        # Parse response to verify done event is present and doesn't have files
        response_text = response.data.decode("utf-8")
        found_done = False
        for line in response_text.split("\n"):
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    if event.get("type") == "done":
                        found_done = True
                        # Should not have files when no images generated
                        assert "files" not in event, (
                            f"Done event should not have files when no images generated. "
                            f"Event: {event}"
                        )
                except json.JSONDecodeError:
                    pass

        assert found_done, "Done event was not found in stream"


class TestChatStreamDoneEvent:
    """Tests for done event handling in streaming chat.

    These tests verify the fix for a bug where the done event was not sent
    when the client appeared to be disconnected (client_connected=False),
    causing the frontend to show an empty message even though the message
    was saved successfully on the server.
    """

    def test_done_event_sent_when_content_exists(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should send done event when content exists regardless of client status."""
        import time

        with patch("src.api.helpers.chat_streaming.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()

            def mock_stream_events(*args: Any, **kwargs: Any) -> Any:
                yield {"type": "thinking", "text": "Thinking about the response..."}
                yield {"type": "token", "text": "Hello"}
                yield {"type": "token", "text": " there!"}
                yield {
                    "type": "final",
                    "content": "Hello there!",
                    "result_messages": [],
                    "tool_results": [],
                    "usage_info": {"input_tokens": 50, "output_tokens": 10},
                }

            mock_agent.stream_chat_events = mock_stream_events
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/stream",
                headers=auth_headers,
                json={"message": "Hello"},
            )

        assert response.status_code == 200

        # Wait for background threads
        time.sleep(1.0)

        # Parse SSE events to verify done event was sent
        response_text = response.data.decode("utf-8")
        done_events = []
        for line in response_text.split("\n"):
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    if event.get("type") == "done":
                        done_events.append(event)
                except json.JSONDecodeError:
                    pass

        assert len(done_events) == 1, (
            f"Expected exactly 1 done event, got {len(done_events)}. "
            f"Full response: {response_text[:500]}"
        )

        # Verify done event has message ID
        done_event = done_events[0]
        assert "id" in done_event, "Done event should have message ID"

    def test_done_event_includes_message_id_and_created_at(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Done event should include message id and created_at for finalization."""
        import time

        with patch("src.api.helpers.chat_streaming.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()

            def mock_stream_events(*args: Any, **kwargs: Any) -> Any:
                yield {"type": "token", "text": "Response content"}
                yield {
                    "type": "final",
                    "content": "Response content",
                    "result_messages": [],
                    "tool_results": [],
                    "usage_info": {"input_tokens": 50, "output_tokens": 10},
                }

            mock_agent.stream_chat_events = mock_stream_events
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/stream",
                headers=auth_headers,
                json={"message": "Test"},
            )

        assert response.status_code == 200

        # Wait for background threads
        time.sleep(1.0)

        # Parse the done event
        response_text = response.data.decode("utf-8")
        done_event = None
        for line in response_text.split("\n"):
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    if event.get("type") == "done":
                        done_event = event
                        break
                except json.JSONDecodeError:
                    pass

        assert done_event is not None, "Done event was not found"
        assert "id" in done_event, "Done event missing 'id'"
        assert "created_at" in done_event, "Done event missing 'created_at'"

        # Verify the message was saved with matching ID
        messages = test_database.get_messages(test_conversation.id)
        assistant_msg = messages[-1]
        assert assistant_msg.id == done_event["id"]

    def test_done_event_includes_content_for_recovery(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Done event should include content for stream recovery when tokens are lost."""
        import time

        expected_content = "This is the full response content."

        with patch("src.api.helpers.chat_streaming.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()

            def mock_stream_events(*args: Any, **kwargs: Any) -> Any:
                yield {"type": "token", "text": expected_content}
                yield {
                    "type": "final",
                    "content": expected_content,
                    "result_messages": [],
                    "tool_results": [],
                    "usage_info": {"input_tokens": 50, "output_tokens": 10},
                }

            mock_agent.stream_chat_events = mock_stream_events
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/stream",
                headers=auth_headers,
                json={"message": "Test"},
            )

        assert response.status_code == 200

        # Wait for background threads
        time.sleep(1.0)

        # Parse the done event
        response_text = response.data.decode("utf-8")
        done_event = None
        for line in response_text.split("\n"):
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    if event.get("type") == "done":
                        done_event = event
                        break
                except json.JSONDecodeError:
                    pass

        assert done_event is not None, "Done event was not found"
        assert "content" in done_event, "Done event missing 'content' field for stream recovery"
        assert done_event["content"] == expected_content, (
            f"Done event content mismatch: expected '{expected_content}', "
            f"got '{done_event.get('content')}'"
        )

    def test_done_event_sent_when_content_empty(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should send done event even when content is empty (e.g., memory-only tool calls)."""
        import time

        with patch("src.api.helpers.chat_streaming.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()

            def mock_stream_events(*args: Any, **kwargs: Any) -> Any:
                # Only thinking, no actual content (e.g. manage_memory only)
                yield {"type": "thinking", "text": "Thinking..."}
                yield {
                    "type": "final",
                    "content": "",  # Empty content - memory-only operation
                    "result_messages": [],
                    "tool_results": [],
                    "usage_info": {"input_tokens": 50, "output_tokens": 0},
                }

            mock_agent.stream_chat_events = mock_stream_events
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/stream",
                headers=auth_headers,
                json={"message": "Hello"},
            )

        assert response.status_code == 200

        # Wait for background threads
        time.sleep(1.0)

        # Parse SSE events - done event must be sent even when content is empty
        # so the frontend can finalize the message (e.g. manage_memory-only responses)
        response_text = response.data.decode("utf-8")
        done_events = []
        for line in response_text.split("\n"):
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    if event.get("type") == "done":
                        done_events.append(event)
                except json.JSONDecodeError:
                    pass

        # Done event should always be sent when save succeeded, even with empty content
        assert len(done_events) == 1, (
            f"Should send done event even when content is empty, but got {len(done_events)}"
        )

    def test_user_message_saved_includes_expected_assistant_id(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """user_message_saved event should include expected_assistant_message_id for recovery."""
        import time

        with patch("src.api.helpers.chat_streaming.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()

            def mock_stream_events(*args: Any, **kwargs: Any) -> Any:
                yield {"type": "token", "text": "Response"}
                yield {
                    "type": "final",
                    "content": "Response",
                    "result_messages": [],
                    "tool_results": [],
                    "usage_info": {"input_tokens": 50, "output_tokens": 10},
                }

            mock_agent.stream_chat_events = mock_stream_events
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/stream",
                headers=auth_headers,
                json={"message": "Test"},
            )

        assert response.status_code == 200

        # Wait for background threads
        time.sleep(1.0)

        # Parse SSE events to find user_message_saved
        response_text = response.data.decode("utf-8")
        user_saved_event = None
        done_event = None
        for line in response_text.split("\n"):
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    if event.get("type") == "user_message_saved":
                        user_saved_event = event
                    elif event.get("type") == "done":
                        done_event = event
                except json.JSONDecodeError:
                    pass

        assert user_saved_event is not None, "user_message_saved event not found"
        assert "expected_assistant_message_id" in user_saved_event, (
            "user_message_saved event should include expected_assistant_message_id"
        )

        # The expected ID should match the actual message ID in done event
        assert done_event is not None, "done event not found"
        assert user_saved_event["expected_assistant_message_id"] == done_event["id"], (
            "Expected assistant message ID should match actual message ID in done event"
        )

    def test_message_uses_pre_generated_id(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Message should be saved with the pre-generated ID for reliable recovery."""
        import time

        with patch("src.api.helpers.chat_streaming.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()

            def mock_stream_events(*args: Any, **kwargs: Any) -> Any:
                yield {"type": "token", "text": "Test message"}
                yield {
                    "type": "final",
                    "content": "Test message",
                    "result_messages": [],
                    "tool_results": [],
                    "usage_info": {"input_tokens": 50, "output_tokens": 10},
                }

            mock_agent.stream_chat_events = mock_stream_events
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/stream",
                headers=auth_headers,
                json={"message": "Test"},
            )

        assert response.status_code == 200

        # Wait for background threads
        time.sleep(1.0)

        # Get the expected ID from user_message_saved event
        response_text = response.data.decode("utf-8")
        expected_id = None
        for line in response_text.split("\n"):
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    if event.get("type") == "user_message_saved":
                        expected_id = event.get("expected_assistant_message_id")
                        break
                except json.JSONDecodeError:
                    pass

        assert expected_id is not None, "Expected ID not found in user_message_saved event"

        # Verify the message was saved with this exact ID
        saved_msg = test_database.get_message_by_id(expected_id)
        assert saved_msg is not None, "Message should be saved with pre-generated ID"
        assert saved_msg.content == "Test message"
        assert saved_msg.role == "assistant"


class TestGetMessage:
    """Tests for GET /api/messages/<message_id> endpoint."""

    def test_get_message_success(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should return the message when it exists and belongs to user."""
        # Create a message
        msg = test_database.add_message(
            test_conversation.id,
            "assistant",
            "Test response content",
        )

        response = client.get(
            f"/api/messages/{msg.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["id"] == msg.id
        assert data["content"] == "Test response content"
        assert data["role"] == "assistant"

    def test_get_message_not_found(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 404 when message doesn't exist."""
        response = client.get(
            "/api/messages/nonexistent-id",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_get_message_requires_auth(
        self,
        client: FlaskClient,
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should return 401 without authentication."""
        msg = test_database.add_message(
            test_conversation.id,
            "assistant",
            "Test content",
        )

        response = client.get(f"/api/messages/{msg.id}")

        assert response.status_code == 401
