"""
Add weather_cache table for storing weather forecast data.

Weather data from Yr.no is cached in SQLite to be shared across multiple
uwsgi workers. The cache includes a TTL (time-to-live) to ensure data is
refreshed periodically (default: 6 hours, as weather forecasts don't change
that frequently).
"""

from yoyo import step

steps = [
    step(
        """
        CREATE TABLE IF NOT EXISTS weather_cache (
            location TEXT PRIMARY KEY,
            forecast_data TEXT NOT NULL,
            cached_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        """,
        "DROP TABLE IF EXISTS weather_cache",
    ),
    step(
        """
        CREATE INDEX IF NOT EXISTS idx_weather_cache_expires_at
        ON weather_cache(expires_at)
        """,
        "DROP INDEX IF EXISTS idx_weather_cache_expires_at",
    ),
]
