"""Unit tests for language extraction from metadata."""

from src.api.utils import extract_language_from_metadata


class TestExtractLanguageFromMetadata:
    """Tests for extract_language_from_metadata function."""

    def test_returns_none_for_none_metadata(self) -> None:
        """Returns None when metadata is None."""
        assert extract_language_from_metadata(None) is None

    def test_returns_none_for_empty_metadata(self) -> None:
        """Returns None when metadata is empty dict."""
        assert extract_language_from_metadata({}) is None

    def test_returns_none_for_missing_language_key(self) -> None:
        """Returns None when metadata has no language key."""
        assert extract_language_from_metadata({"sources": []}) is None

    def test_returns_none_for_non_string_language(self) -> None:
        """Returns None when language value is not a string."""
        assert extract_language_from_metadata({"language": 123}) is None
        assert extract_language_from_metadata({"language": None}) is None
        assert extract_language_from_metadata({"language": ["en"]}) is None

    def test_extracts_simple_language_code(self) -> None:
        """Extracts simple ISO 639-1 language codes."""
        assert extract_language_from_metadata({"language": "en"}) == "en"
        assert extract_language_from_metadata({"language": "cs"}) == "cs"
        assert extract_language_from_metadata({"language": "de"}) == "de"

    def test_normalizes_uppercase_codes(self) -> None:
        """Normalizes uppercase language codes to lowercase."""
        assert extract_language_from_metadata({"language": "EN"}) == "en"
        assert extract_language_from_metadata({"language": "CS"}) == "cs"

    def test_extracts_primary_language_from_regional_codes(self) -> None:
        """Extracts primary language from regional codes like en-US."""
        assert extract_language_from_metadata({"language": "en-US"}) == "en"
        assert extract_language_from_metadata({"language": "en-GB"}) == "en"
        assert extract_language_from_metadata({"language": "cs-CZ"}) == "cs"
        assert extract_language_from_metadata({"language": "zh-TW"}) == "zh"

    def test_handles_mixed_case_regional_codes(self) -> None:
        """Handles mixed case regional codes."""
        assert extract_language_from_metadata({"language": "EN-US"}) == "en"
        assert extract_language_from_metadata({"language": "En-Gb"}) == "en"

    def test_truncates_long_codes_to_two_chars(self) -> None:
        """Truncates codes longer than 2 characters."""
        assert extract_language_from_metadata({"language": "eng"}) == "en"
        assert extract_language_from_metadata({"language": "ces"}) == "ce"

    def test_returns_none_for_empty_string(self) -> None:
        """Returns None for empty string language value."""
        assert extract_language_from_metadata({"language": ""}) is None

    def test_preserves_other_metadata_fields(self) -> None:
        """Does not interfere with other metadata fields."""
        metadata = {
            "language": "en",
            "sources": [{"title": "Test", "url": "http://example.com"}],
            "generated_images": [{"prompt": "test"}],
        }
        assert extract_language_from_metadata(metadata) == "en"
