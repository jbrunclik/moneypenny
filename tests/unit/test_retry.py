"""Tests for transient-error detection in src/agent/retry.py."""

from src.agent.retry import is_transient_error


class TestIsTransientError:
    def test_typed_transient_exception(self) -> None:
        assert is_transient_error(TimeoutError("read timed out")) is True

    def test_non_transient_exception(self) -> None:
        assert is_transient_error(ValueError("bad input")) is False

    def test_transient_pattern_ignored_in_payload_tail(self) -> None:
        # A tool payload embedded in an exception message must not make the
        # error look transient: patterns only count near the message start.
        err = ValueError("Unexpected tool output: " + "x" * 400 + " connection reset by peer")
        assert is_transient_error(err) is False

    def test_transient_detected_via_cause_chain(self) -> None:
        # Provider SDKs wrap transient errors in their own exception types.
        inner = TimeoutError("read timed out")
        outer = RuntimeError("wrapped by SDK")
        outer.__cause__ = inner
        assert is_transient_error(outer) is True

    def test_transient_detected_via_context_chain(self) -> None:
        inner = ConnectionError("connection refused")
        outer = RuntimeError("while handling request")
        outer.__context__ = inner
        assert is_transient_error(outer) is True

    def test_transient_pattern_near_message_start_still_matches(self) -> None:
        assert is_transient_error(Exception("429 Resource has been exhausted")) is True

    def test_cause_cycle_does_not_hang(self) -> None:
        a = RuntimeError("a")
        b = RuntimeError("b")
        a.__cause__ = b
        b.__cause__ = a
        assert is_transient_error(a) is False
