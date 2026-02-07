"""Unit tests for language detection from response content."""

from src.agent.content import detect_response_language


class TestDetectResponseLanguage:
    """Tests for detect_response_language function (server-side langdetect)."""

    def test_returns_none_for_empty_text(self) -> None:
        """Returns None when text is empty."""
        assert detect_response_language("") is None

    def test_returns_none_for_short_text(self) -> None:
        """Returns None when text is too short for reliable detection."""
        assert detect_response_language("Hi") is None
        assert detect_response_language("OK") is None

    def test_detects_english(self) -> None:
        """Should detect English text correctly."""
        result = detect_response_language(
            "This is a longer English sentence that should be detected correctly."
        )
        assert result == "en"

    def test_detects_czech(self) -> None:
        """Should detect Czech text correctly."""
        result = detect_response_language(
            "Toto je delší česká věta, která by měla být správně detekována."
        )
        assert result == "cs"

    def test_detects_german(self) -> None:
        """Should detect German text correctly."""
        result = detect_response_language(
            "Dies ist ein längerer deutscher Satz, der korrekt erkannt werden sollte."
        )
        assert result == "de"

    def test_returns_two_char_code(self) -> None:
        """Should return ISO 639-1 (2-char) language codes."""
        result = detect_response_language(
            "This is a test sentence in English with enough text for detection."
        )
        assert result is not None
        assert len(result) == 2
        assert result.islower()

    def test_returns_none_for_whitespace_only(self) -> None:
        """Returns None for whitespace-only text."""
        assert detect_response_language("   \n\t  ") is None
