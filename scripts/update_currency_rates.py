#!/usr/bin/env python3
"""Currency rate update script for AI Chatbot.

Fetches current USD exchange rates from a free API and saves them to the database.
The application loads rates from the database at runtime.

Usage:
    python scripts/update_currency_rates.py

This script is designed to be run via systemd timer (daily) or manually as needed.

API: Uses exchangerate-api.com free tier (no API key required, 1500 requests/month)
Fallback: If API fails, keeps existing rates unchanged.
"""

import sys
from pathlib import Path

import httpx

# Add parent directory to path so we can import from src
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Free API endpoint (no API key required)
# Alternative: https://open.er-api.com/v6/latest/USD (also free, no key)
API_URL = "https://open.er-api.com/v6/latest/USD"
API_TIMEOUT = 30  # seconds

# Currencies we care about (must include USD)
TARGET_CURRENCIES = ["USD", "CZK", "EUR", "GBP"]


def fetch_rates() -> dict[str, float] | None:
    """Fetch current exchange rates from API.

    Returns:
        Dictionary of currency code to rate (USD base), or None on error.
    """
    try:
        logger.info("Fetching currency rates", extra={"url": API_URL})

        with httpx.Client(timeout=API_TIMEOUT) as client:
            response = client.get(API_URL)
            response.raise_for_status()

        data = response.json()

        # Validate response structure
        if data.get("result") != "success":
            logger.error(
                "API returned error",
                extra={"response": data.get("error-type", "unknown")},
            )
            return None

        rates = data.get("rates", {})
        if not rates:
            logger.error("API response missing rates")
            return None

        # Extract only the currencies we need
        filtered_rates: dict[str, float] = {}
        for currency in TARGET_CURRENCIES:
            if currency in rates:
                filtered_rates[currency] = float(rates[currency])
            else:
                logger.warning(f"Currency {currency} not found in API response")

        # USD should always be 1.0
        filtered_rates["USD"] = 1.0

        logger.info(
            "Rates fetched successfully",
            extra={"rates": filtered_rates, "source_time": data.get("time_last_update_utc")},
        )
        return filtered_rates

    except httpx.TimeoutException:
        logger.error("API request timed out", extra={"timeout": API_TIMEOUT})
        return None
    except httpx.HTTPStatusError as e:
        logger.error(
            "API request failed",
            extra={"status_code": e.response.status_code, "url": str(e.request.url)},
        )
        return None
    except httpx.RequestError as e:
        logger.error("Network error fetching rates", extra={"error": str(e)}, exc_info=True)
        return None
    except (ValueError, KeyError) as e:
        logger.error("Error parsing API response", extra={"error": str(e)}, exc_info=True)
        return None


def get_existing_rates() -> dict[str, float]:
    """Get existing rates from DB, or return defaults from Config.

    Returns:
        Dictionary of currency code to rate.
    """
    db_rates = db.get_currency_rates()
    if db_rates:
        return db_rates
    return Config.CURRENCY_RATES.copy()


def main() -> int:
    """Update currency rates from API.

    Returns:
        0 if rates updated successfully, 1 if fetch failed (existing rates kept).
    """
    logger.info("Starting currency rate update")

    # Load existing rates as fallback
    existing_rates = get_existing_rates()
    logger.debug("Existing rates loaded", extra={"rates": existing_rates})

    # Fetch new rates
    new_rates = fetch_rates()

    if new_rates is None:
        logger.warning(
            "Failed to fetch new rates, keeping existing",
            extra={"existing_rates": existing_rates},
        )
        return 1

    # Compare rates and log changes
    for currency, rate in new_rates.items():
        old_rate = existing_rates.get(currency)
        if old_rate and old_rate != rate:
            change_pct = ((rate - old_rate) / old_rate) * 100
            logger.info(
                f"Rate changed for {currency}",
                extra={
                    "currency": currency,
                    "old_rate": old_rate,
                    "new_rate": rate,
                    "change_pct": round(change_pct, 2),
                },
            )

    # Save new rates to database
    db.set_currency_rates(new_rates)
    logger.info("Currency rate update completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
