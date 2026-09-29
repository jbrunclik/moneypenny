"""Unit tests for cleanup_and_save in src/api/helpers/stream_producer.py."""


class TestCleanupAndSave:
    """Tests for the cleanup_and_save function.

    This function is responsible for saving messages when the generator exits
    without saving (e.g., due to GeneratorExit from client disconnect).
    """

    def test_cleanup_saves_when_generator_exits_without_saving(self) -> None:
        """Regression: cleanup thread should save when generator_done_event is set but saved=False.

        Bug: When a mobile client locks the screen, the browser disconnects and
        Flask/Gunicorn calls generator.close(), raising GeneratorExit. This exception
        bypasses _finalize_stream (which does the save). The generator's finally block
        sets generator_done_event, but no save happened.

        The old code returned early when generator_done_event was set, assuming
        the generator had saved. But GeneratorExit can kill the generator before save.

        The fix: always check final_results["saved"] even when generator_done_event is set.
        """
        import threading
        from unittest.mock import MagicMock

        from src.api.helpers.stream_producer import cleanup_and_save

        # Create a stream thread that's already done
        stream_thread = MagicMock(spec=threading.Thread)
        stream_thread.is_alive.return_value = False  # Thread completed
        stream_thread.join = MagicMock()

        # Simulate the scenario: generator was killed by GeneratorExit
        # - ready=True (stream thread finished and produced results)
        # - saved=False (GeneratorExit killed generator before _finalize_stream)
        final_results = {
            "ready": True,
            "saved": False,
            "clean_content": "This is the response content",
            "metadata": {"language": "en"},
            "tool_results": [],
            "usage_info": {"input_tokens": 100, "output_tokens": 50},
        }

        save_lock = threading.Lock()
        generator_done_event = threading.Event()
        generator_done_event.set()  # Generator's finally block ran (sets this)

        save_func = MagicMock(return_value=MagicMock(message_id="msg-123"))

        cleanup_and_save(
            stream_thread=stream_thread,
            final_results=final_results,
            save_lock=save_lock,
            generator_done_event=generator_done_event,
            conv_id="conv-123",
            user_id="user-456",
            save_func=save_func,
        )

        # The save function MUST have been called even though generator_done_event was set
        save_func.assert_called_once()
        # final_results["saved"] should be set to True
        assert final_results["saved"] is True

    def test_cleanup_does_not_double_save(self) -> None:
        """When generator already saved (saved=True), cleanup should not save again."""
        import threading
        from unittest.mock import MagicMock

        from src.api.helpers.stream_producer import cleanup_and_save

        stream_thread = MagicMock(spec=threading.Thread)
        stream_thread.is_alive.return_value = False
        stream_thread.join = MagicMock()

        # Generator successfully saved before exiting
        final_results = {
            "ready": True,
            "saved": True,  # Already saved
            "clean_content": "Response content",
            "metadata": {},
            "tool_results": [],
            "usage_info": {},
        }

        save_lock = threading.Lock()
        generator_done_event = threading.Event()
        generator_done_event.set()

        save_func = MagicMock()

        cleanup_and_save(
            stream_thread=stream_thread,
            final_results=final_results,
            save_lock=save_lock,
            generator_done_event=generator_done_event,
            conv_id="conv-123",
            user_id="user-456",
            save_func=save_func,
        )

        # save_func should NOT be called since saved=True
        save_func.assert_not_called()

    def test_cleanup_saves_empty_content(self) -> None:
        """Should save even when content is empty (e.g. manage_memory-only tool calls)."""
        import threading
        from unittest.mock import MagicMock

        from src.api.helpers.stream_producer import cleanup_and_save

        stream_thread = MagicMock(spec=threading.Thread)
        stream_thread.is_alive.return_value = False
        stream_thread.join = MagicMock()

        final_results = {
            "ready": True,
            "saved": False,
            "clean_content": "",  # Empty content - memory-only operation
            "metadata": {},
            "tool_results": [],
            "usage_info": {},
        }

        save_lock = threading.Lock()
        generator_done_event = threading.Event()
        generator_done_event.set()

        save_func = MagicMock()

        cleanup_and_save(
            stream_thread=stream_thread,
            final_results=final_results,
            save_lock=save_lock,
            generator_done_event=generator_done_event,
            conv_id="conv-123",
            user_id="user-456",
            save_func=save_func,
        )

        # save_func should be called even when content is empty
        # (e.g. manage_memory-only responses still need to be persisted)
        save_func.assert_called_once()

    def test_cleanup_does_not_save_when_not_ready(self) -> None:
        """Should not save when results are not ready (stream thread didn't complete)."""
        import threading
        from unittest.mock import MagicMock

        from src.api.helpers.stream_producer import cleanup_and_save

        stream_thread = MagicMock(spec=threading.Thread)
        stream_thread.is_alive.return_value = False
        stream_thread.join = MagicMock()

        final_results = {
            "ready": False,  # Stream thread didn't produce final results
            "saved": False,
            "clean_content": "Content",
            "metadata": {},
            "tool_results": [],
            "usage_info": {},
        }

        save_lock = threading.Lock()
        generator_done_event = threading.Event()
        generator_done_event.set()

        save_func = MagicMock()

        cleanup_and_save(
            stream_thread=stream_thread,
            final_results=final_results,
            save_lock=save_lock,
            generator_done_event=generator_done_event,
            conv_id="conv-123",
            user_id="user-456",
            save_func=save_func,
        )

        # save_func should NOT be called since ready=False
        save_func.assert_not_called()
