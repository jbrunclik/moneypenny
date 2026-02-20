"""Unit tests for src/utils/costs.py."""

import pytest

from src.utils.costs import (
    calculate_image_generation_cost,
    calculate_token_cost,
    calculate_total_cost,
    convert_currency,
    format_cost,
    get_model_pricing,
)


class TestGetModelPricing:
    """Tests for get_model_pricing function."""

    def test_flash_model_pricing(self) -> None:
        """Test pricing for gemini-3-flash-preview model."""
        pricing = get_model_pricing("gemini-3-flash-preview")
        assert pricing["input"] == 0.075
        assert pricing["output"] == 0.30

    def test_pro_model_pricing(self) -> None:
        """Test pricing for gemini-3.1-pro-preview model."""
        pricing = get_model_pricing("gemini-3.1-pro-preview")
        assert pricing["input"] == 2.00
        assert pricing["output"] == 12.00

    def test_image_model_pricing(self) -> None:
        """Test pricing for image generation model."""
        pricing = get_model_pricing("gemini-3-pro-image-preview")
        assert pricing["input"] == 2.00
        assert pricing["output"] == 12.00

    def test_unknown_model_falls_back_to_flash(self) -> None:
        """Unknown models should fall back to flash pricing."""
        pricing = get_model_pricing("unknown-model-xyz")
        flash_pricing = get_model_pricing("gemini-3-flash-preview")
        assert pricing == flash_pricing


class TestCalculateTokenCost:
    """Tests for calculate_token_cost function."""

    def test_flash_model_cost_one_million_tokens(self) -> None:
        """Calculate cost for 1M input + 1M output tokens on flash."""
        # 1M input at $0.075 + 1M output at $0.30 = $0.375
        cost = calculate_token_cost("gemini-3-flash-preview", 1_000_000, 1_000_000)
        assert cost == pytest.approx(0.375)

    def test_pro_model_cost_one_million_tokens(self) -> None:
        """Calculate cost for 1M input + 1M output tokens on pro."""
        # 1M input at $2.00 + 1M output at $12.00 = $14.00
        cost = calculate_token_cost("gemini-3.1-pro-preview", 1_000_000, 1_000_000)
        assert cost == pytest.approx(14.00)

    def test_zero_tokens_zero_cost(self) -> None:
        """Zero tokens should result in zero cost."""
        cost = calculate_token_cost("gemini-3-flash-preview", 0, 0)
        assert cost == 0.0

    def test_realistic_conversation_cost(self) -> None:
        """Test cost for a typical conversation (5000 input + 1000 output)."""
        cost = calculate_token_cost("gemini-3-flash-preview", 5000, 1000)
        expected = (5000 / 1_000_000 * 0.075) + (1000 / 1_000_000 * 0.30)
        assert cost == pytest.approx(expected)

    def test_input_only(self) -> None:
        """Test cost with only input tokens."""
        cost = calculate_token_cost("gemini-3-flash-preview", 10000, 0)
        expected = 10000 / 1_000_000 * 0.075
        assert cost == pytest.approx(expected)

    def test_output_only(self) -> None:
        """Test cost with only output tokens."""
        cost = calculate_token_cost("gemini-3-flash-preview", 0, 10000)
        expected = 10000 / 1_000_000 * 0.30
        assert cost == pytest.approx(expected)


class TestCalculateImageGenerationCost:
    """Tests for calculate_image_generation_cost function."""

    def test_with_all_token_types(self) -> None:
        """Test cost calculation with all token types."""
        usage = {
            "prompt_token_count": 100,
            "candidates_token_count": 500,
            "thoughts_token_count": 100,
        }
        cost = calculate_image_generation_cost(usage)
        # Input: 100/1M * $2.00 = $0.0002
        # Output: (500 + 100)/1M * $12.00 = $0.0072
        expected = (100 / 1_000_000 * 2.0) + (600 / 1_000_000 * 12.0)
        assert cost == pytest.approx(expected)

    def test_empty_usage_metadata(self) -> None:
        """Empty usage metadata should return zero cost."""
        cost = calculate_image_generation_cost({})
        assert cost == 0.0

    def test_missing_token_counts(self) -> None:
        """Missing token counts should be treated as zero."""
        usage = {"prompt_token_count": 100}  # missing candidates and thoughts
        cost = calculate_image_generation_cost(usage)
        expected = 100 / 1_000_000 * 2.0  # Only input cost
        assert cost == pytest.approx(expected)


class TestCalculateTotalCost:
    """Tests for calculate_total_cost function."""

    def test_tokens_only(self) -> None:
        """Test total cost with only tokens (no image generation)."""
        cost = calculate_total_cost("gemini-3-flash-preview", 5000, 1000)
        expected = calculate_token_cost("gemini-3-flash-preview", 5000, 1000)
        assert cost == pytest.approx(expected)

    def test_with_image_generation(self) -> None:
        """Test total cost including image generation."""
        image_cost = 0.05
        cost = calculate_total_cost(
            "gemini-3-flash-preview", 5000, 1000, image_generation_cost=image_cost
        )
        token_cost = calculate_token_cost("gemini-3-flash-preview", 5000, 1000)
        assert cost == pytest.approx(token_cost + image_cost)

    def test_zero_tokens_with_image_cost(self) -> None:
        """Test cost with only image generation (no tokens)."""
        image_cost = 0.10
        cost = calculate_total_cost(
            "gemini-3-flash-preview", 0, 0, image_generation_cost=image_cost
        )
        assert cost == pytest.approx(image_cost)


class TestConvertCurrency:
    """Tests for convert_currency function."""

    # Fixed rates for testing (mocked to avoid dependency on DB/Config values)
    MOCK_RATES = {"CZK": 23.0, "EUR": 0.92, "GBP": 0.79}

    @pytest.fixture(autouse=True)
    def mock_rates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock get_currency_rates to return fixed test values."""
        monkeypatch.setattr("src.utils.costs.get_currency_rates", lambda: self.MOCK_RATES)

    def test_usd_to_usd(self) -> None:
        """USD to USD conversion should be 1:1."""
        assert convert_currency(1.0, "USD") == 1.0
        assert convert_currency(10.5, "USD") == 10.5

    def test_usd_to_czk(self) -> None:
        """USD to CZK conversion."""
        # Using mocked rate of 23.0
        assert convert_currency(1.0, "CZK") == 23.0
        assert convert_currency(0.5, "CZK") == 11.5

    def test_usd_to_eur(self) -> None:
        """USD to EUR conversion."""
        # Using mocked rate of 0.92
        assert convert_currency(1.0, "EUR") == 0.92
        assert convert_currency(10.0, "EUR") == pytest.approx(9.2)

    def test_usd_to_gbp(self) -> None:
        """USD to GBP conversion."""
        # Using mocked rate of 0.79
        assert convert_currency(1.0, "GBP") == 0.79

    def test_unknown_currency_uses_default_rate(self) -> None:
        """Unknown currency should use 1.0 rate (same as USD)."""
        assert convert_currency(10.0, "XYZ") == 10.0

    def test_case_insensitive(self) -> None:
        """Currency codes should be case insensitive."""
        assert convert_currency(1.0, "czk") == convert_currency(1.0, "CZK")


class TestFormatCost:
    """Tests for format_cost function."""

    def test_format_usd(self) -> None:
        """Format USD amounts."""
        assert format_cost(0.0523, "USD") == "$0.0523"
        assert format_cost(1.0, "USD") == "$1.0000"

    def test_format_czk(self) -> None:
        """Format CZK amounts."""
        assert format_cost(1.15, "CZK") == "1.15 Kč"
        assert format_cost(23.50, "CZK") == "23.50 Kč"

    def test_format_eur(self) -> None:
        """Format EUR amounts."""
        assert format_cost(0.0523, "EUR") == "€0.0523"

    def test_format_gbp(self) -> None:
        """Format GBP amounts."""
        assert format_cost(0.0523, "GBP") == "£0.0523"

    def test_format_unknown_currency(self) -> None:
        """Unknown currency should use generic format."""
        assert format_cost(1.5, "XYZ") == "1.5000 XYZ"
