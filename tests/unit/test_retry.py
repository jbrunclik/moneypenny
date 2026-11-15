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


class TestTheInstalledSdksErrors:
    """What langchain-google-genai 4.x and google-genai actually raise (Nov 2026
    audit: the retry matched google.api_core classes nothing raises any more,
    so 500, 504 and network timeouts were never retried)."""

    @staticmethod
    def _server(code: int, status: str) -> Exception:
        from langchain_google_genai.chat_models import GoogleAPIError

        return GoogleAPIError(code=code, response_json={"error": {"status": status}})

    def test_a_500_is_retried(self) -> None:
        assert is_transient_error(self._server(500, "INTERNAL")) is True

    def test_a_504_is_retried(self) -> None:
        assert is_transient_error(self._server(504, "DEADLINE_EXCEEDED")) is True

    def test_a_rate_limit_is_retried(self) -> None:
        from langchain_google_genai.chat_models import GoogleRateLimitError

        assert is_transient_error(GoogleRateLimitError("Error calling model 'x'")) is True

    def test_network_failures_are_retried(self) -> None:
        import httpx

        assert is_transient_error(httpx.ReadTimeout("The read operation timed out")) is True
        assert is_transient_error(httpx.ConnectError("[Errno 104] reset")) is True

    def test_the_gemini_clients_network_failures_are_retried(self) -> None:
        # google-genai 3.x sends requests through httpx2 (pydantic's fork),
        # whose exceptions are not httpx's
        import httpx2

        assert is_transient_error(httpx2.ReadTimeout("The read operation timed out")) is True
        assert is_transient_error(httpx2.ConnectError("[Errno 104] reset")) is True

    def test_a_bad_request_is_not_retried(self) -> None:
        from langchain_google_genai.chat_models import GoogleInvalidRequestError

        assert is_transient_error(GoogleInvalidRequestError("Error calling model 'x'")) is False

    def test_a_context_overflow_is_not_retried(self) -> None:
        from langchain_google_genai.chat_models import GoogleContextOverflowError

        err = GoogleContextOverflowError(code=400, response_json={"error": {"status": "x"}})
        assert is_transient_error(err) is False
