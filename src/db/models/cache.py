"""Cache database operations mixin.

Contains all methods for caching operations including:
- Dashboard cache (planner dashboard data)
- Calendar cache (available calendars list)
- Weather cache (forecast data)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class CacheMixin:
    """Mixin providing cache-related database operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    # ============================================================================
    # Dashboard Cache Operations
    # ============================================================================

    def get_cached_dashboard(self, user_id: str) -> dict[str, Any] | None:
        """Get cached dashboard if not expired.

        Args:
            user_id: The user ID

        Returns:
            Dashboard data dict if cached and not expired, None otherwise
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """
                SELECT dashboard_data, expires_at
                FROM dashboard_cache
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

            if not row:
                return None

            # Check if expired
            expires_at = datetime.fromisoformat(row[1])
            if datetime.utcnow() >= expires_at:
                # Expired - delete and return None
                self.delete_cached_dashboard(user_id)
                return None

            # Deserialize and return
            result: dict[str, Any] = json.loads(row[0])
            return result

    def cache_dashboard(
        self,
        user_id: str,
        dashboard_data: dict[str, Any],
        ttl_seconds: int = 300,
    ) -> None:
        """Cache dashboard data with TTL.

        Args:
            user_id: The user ID
            dashboard_data: Dashboard data dict to cache
            ttl_seconds: Time-to-live in seconds (default: 300 = 5 minutes)
        """
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds)

        # Serialize dashboard
        dashboard_json = json.dumps(dashboard_data)

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """
                INSERT OR REPLACE INTO dashboard_cache
                (user_id, dashboard_data, cached_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, dashboard_json, now.isoformat(), expires_at.isoformat()),
            )
            conn.commit()

    def delete_cached_dashboard(self, user_id: str) -> None:
        """Delete cached dashboard for force refresh.

        Args:
            user_id: The user ID
        """
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "DELETE FROM dashboard_cache WHERE user_id = ?",
                (user_id,),
            )
            conn.commit()

    def cleanup_expired_dashboard_cache(self) -> int:
        """Delete all expired cache entries.

        Returns:
            Number of entries deleted
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM dashboard_cache WHERE expires_at < ?",
                (datetime.utcnow().isoformat(),),
            )
            conn.commit()
            return cursor.rowcount

    def invalidate_dashboard_cache(self, user_id: str) -> None:
        """Invalidate dashboard cache when calendar selection changes.

        Args:
            user_id: User ID
        """
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "DELETE FROM dashboard_cache WHERE user_id = ?",
                (user_id,),
            )
            conn.commit()
        logger.debug("Dashboard cache invalidated", extra={"user_id": user_id})

    # ============================================================================
    # Calendar Cache Operations
    # ============================================================================

    def get_cached_calendars(self, user_id: str) -> dict[str, Any] | None:
        """Get cached available calendars for a user.

        Args:
            user_id: User ID

        Returns:
            Calendar list data dict if cached and not expired, None otherwise
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """
                SELECT calendars_data FROM calendar_cache
                WHERE user_id = ? AND expires_at > ?
                """,
                (user_id, datetime.now().isoformat()),
            )
            row = cursor.fetchone()

            if row:
                logger.debug("Calendar cache hit", extra={"user_id": user_id})
                calendars_data: dict[str, Any] = json.loads(row["calendars_data"])
                return calendars_data

            logger.debug("Calendar cache miss", extra={"user_id": user_id})
            return None

    def cache_calendars(
        self, user_id: str, calendars_data: dict[str, Any], ttl_seconds: int = 3600
    ) -> None:
        """Cache available calendars for a user.

        Args:
            user_id: User ID
            calendars_data: Calendar list data dict to cache
            ttl_seconds: Time-to-live in seconds (default: 3600 = 1 hour)
        """
        cached_at = datetime.now()
        expires_at = cached_at + timedelta(seconds=ttl_seconds)
        calendars_json = json.dumps(calendars_data)

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """
                INSERT INTO calendar_cache (user_id, calendars_data, cached_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    calendars_data = excluded.calendars_data,
                    cached_at = excluded.cached_at,
                    expires_at = excluded.expires_at
                """,
                (user_id, calendars_json, cached_at.isoformat(), expires_at.isoformat()),
            )
            conn.commit()

        logger.debug("Calendars cached", extra={"user_id": user_id, "ttl": ttl_seconds})

    def clear_calendar_cache(self, user_id: str) -> None:
        """Clear calendar cache for a user (e.g., on disconnect/reconnect).

        Args:
            user_id: User ID
        """
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "DELETE FROM calendar_cache WHERE user_id = ?",
                (user_id,),
            )
            conn.commit()

        logger.debug("Calendar cache cleared", extra={"user_id": user_id})

    # ============================================================================
    # Weather Cache Operations
    # ============================================================================

    def get_cached_weather(self, location: str) -> dict[str, Any] | None:
        """Get cached weather forecast if not expired.

        Args:
            location: Location string (e.g., "Prague" or "lat,lon")

        Returns:
            Weather forecast data dict if cached and not expired, None otherwise
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """
                SELECT forecast_data, expires_at
                FROM weather_cache
                WHERE location = ?
                """,
                (location,),
            ).fetchone()

            if not row:
                return None

            # Check if expired
            expires_at = datetime.fromisoformat(row[1])
            if datetime.utcnow() >= expires_at:
                # Expired - delete and return None
                self.delete_cached_weather(location)
                return None

            # Deserialize and return
            result: dict[str, Any] = json.loads(row[0])
            return result

    def cache_weather(
        self,
        location: str,
        forecast_data: dict[str, Any],
        ttl_seconds: int = 21600,
    ) -> None:
        """Cache weather forecast data with TTL.

        Args:
            location: Location string (e.g., "Prague" or "lat,lon")
            forecast_data: Weather forecast data dict to cache
            ttl_seconds: Time-to-live in seconds (default: 21600 = 6 hours)
        """
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds)

        # Serialize forecast
        forecast_json = json.dumps(forecast_data)

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """
                INSERT OR REPLACE INTO weather_cache
                (location, forecast_data, cached_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (location, forecast_json, now.isoformat(), expires_at.isoformat()),
            )
            conn.commit()

    def delete_cached_weather(self, location: str) -> None:
        """Delete cached weather for force refresh.

        Args:
            location: Location string
        """
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "DELETE FROM weather_cache WHERE location = ?",
                (location,),
            )
            conn.commit()

    def cleanup_expired_weather_cache(self) -> int:
        """Delete all expired weather cache entries.

        Returns:
            Number of entries deleted
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM weather_cache WHERE expires_at < ?",
                (datetime.utcnow().isoformat(),),
            )
            conn.commit()
            return cursor.rowcount
