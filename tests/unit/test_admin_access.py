"""Who counts as an admin (ADMIN_EMAILS)."""

from datetime import datetime
from unittest.mock import patch

from src.auth.admin import is_admin
from src.config import Config
from src.db.models import User


def _user(email: str) -> User:
    return User(id="u", email=email, name="U", picture=None, created_at=datetime(2026, 10, 25))


def test_listed_email_is_admin_case_insensitively() -> None:
    with patch.object(Config, "ADMIN_EMAILS", ["Admin@Example.com"]):
        assert is_admin(_user("admin@example.com")) is True


def test_unlisted_email_is_not_admin() -> None:
    with patch.object(Config, "ADMIN_EMAILS", ["admin@example.com"]):
        assert is_admin(_user("someone@example.com")) is False


def test_no_admins_configured_means_nobody_is_admin() -> None:
    with patch.object(Config, "ADMIN_EMAILS", []):
        assert is_admin(_user("admin@example.com")) is False
