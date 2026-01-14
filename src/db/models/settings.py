"""App settings database operations mixin.

Contains methods for application-wide settings including:
- Generic key-value settings
- Currency rates
"""

import json
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class SettingsMixin:
    """Mixin providing app settings database operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def get_setting(self, key: str) -> str | None:
        """Get an application setting by key.

        Args:
            key: The setting key

        Returns:
            The setting value, or None if not found
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT value FROM app_settings WHERE key = ?",
                (key,),
            ).fetchone()

            return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        """Set an application setting.

        Args:
            key: The setting key
            value: The setting value (must be a string, use JSON for complex values)
        """
        now = datetime.utcnow().isoformat()
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?
                """,
                (key, value, now, value, now),
            )
            conn.commit()
            logger.debug("Setting updated", extra={"key": key})

    def get_currency_rates(self) -> dict[str, float] | None:
        """Get currency rates from the database.

        Returns:
            Dictionary of currency code to rate, or None if not set
        """
        value = self.get_setting("currency_rates")
        if value:
            try:
                rates: dict[str, float] = json.loads(value)
                return rates
            except json.JSONDecodeError:
                logger.warning("Invalid JSON in currency_rates setting")
        return None

    def set_currency_rates(self, rates: dict[str, float]) -> None:
        """Set currency rates in the database.

        Args:
            rates: Dictionary of currency code to rate (USD base)
        """
        self.set_setting("currency_rates", json.dumps(rates))
        logger.info("Currency rates updated", extra={"rates": rates})
