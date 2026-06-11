"""Tests for the shared, concurrency-safe calendar token refresh (R2).

With multiple gunicorn workers two requests can refresh the same user's
token simultaneously. The losing writer must NOT overwrite the winning
writer's (possibly rotated) refresh token - that would permanently break
future refreshes.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from src.auth.google_calendar import get_valid_access_token


def _make_user(expires_in_minutes: int) -> MagicMock:
    user = MagicMock()
    user.google_calendar_access_token = "old-access"
    user.google_calendar_refresh_token = "old-refresh"
    user.google_calendar_token_expires_at = datetime.now() + timedelta(minutes=expires_in_minutes)
    return user


class TestGetValidAccessToken:
    @patch("src.db.models.db")
    def test_returns_stored_token_when_fresh(self, mock_db: MagicMock) -> None:
        mock_db.get_user_by_id.return_value = _make_user(expires_in_minutes=60)

        assert get_valid_access_token("u1") == "old-access"
        mock_db.refresh_user_google_calendar_tokens.assert_not_called()

    @patch("src.auth.google_calendar.refresh_access_token")
    @patch("src.db.models.db")
    def test_refreshes_and_stores_with_cas(
        self, mock_db: MagicMock, mock_refresh: MagicMock
    ) -> None:
        mock_db.get_user_by_id.return_value = _make_user(expires_in_minutes=2)
        mock_db.refresh_user_google_calendar_tokens.return_value = True
        mock_refresh.return_value = {
            "access_token": "new-access",
            "refresh_token": "rotated-refresh",
            "expires_in": 3600,
        }

        assert get_valid_access_token("u1") == "new-access"

        kwargs = mock_db.refresh_user_google_calendar_tokens.call_args.kwargs
        # CAS guard: only write if the stored refresh token is still the one we used
        assert kwargs["used_refresh_token"] == "old-refresh"
        assert kwargs["refresh_token"] == "rotated-refresh"

    @patch("src.auth.google_calendar.refresh_access_token")
    @patch("src.db.models.db")
    def test_cas_loss_still_returns_valid_token(
        self, mock_db: MagicMock, mock_refresh: MagicMock
    ) -> None:
        """When another worker refreshed first (CAS write fails), our access
        token is still valid to use - it just must not be stored."""
        mock_db.get_user_by_id.return_value = _make_user(expires_in_minutes=2)
        mock_db.refresh_user_google_calendar_tokens.return_value = False
        mock_refresh.return_value = {"access_token": "loser-access", "expires_in": 3600}

        assert get_valid_access_token("u1") == "loser-access"

    @patch("src.db.models.db")
    def test_returns_none_when_not_connected(self, mock_db: MagicMock) -> None:
        mock_db.get_user_by_id.return_value = None
        assert get_valid_access_token("u1") is None


class TestRefreshTokensCompareAndSwap:
    """DB-level CAS semantics on a real database."""

    def test_cas_write_and_reject(self, test_database, test_user) -> None:
        test_database.update_user_google_calendar_tokens(
            test_user.id,
            access_token="a1",
            refresh_token="r1",
            expires_at=datetime.now(),
            email="u@example.com",
        )

        # Winner: stored refresh token matches what was used
        assert test_database.refresh_user_google_calendar_tokens(
            test_user.id,
            used_refresh_token="r1",
            access_token="a2",
            refresh_token="r2",
            expires_at=datetime.now() + timedelta(hours=1),
        )

        # Loser: used the now-replaced refresh token - write must be rejected
        assert not test_database.refresh_user_google_calendar_tokens(
            test_user.id,
            used_refresh_token="r1",
            access_token="a3",
            refresh_token="r3",
            expires_at=datetime.now() + timedelta(hours=1),
        )

        user = test_database.get_user_by_id(test_user.id)
        assert user.google_calendar_access_token == "a2"
        assert user.google_calendar_refresh_token == "r2"
