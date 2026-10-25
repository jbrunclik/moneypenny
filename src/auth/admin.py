"""Admin access (S12): the accounts listed in ADMIN_EMAILS."""

from collections.abc import Callable
from functools import wraps
from typing import Any

from src.api.errors import raise_auth_forbidden_error
from src.config import Config
from src.db.models import User


def is_admin(user: User) -> bool:
    """Whether the user may see the admin page."""
    return user.email.lower() in {email.lower() for email in Config.ADMIN_EMAILS}


def require_admin[F: Callable[..., Any]](f: F) -> F:
    """Refuse non-admins with 403. Goes inside @require_auth, which injects the user."""

    @wraps(f)
    def decorated(user: User, *args: Any, **kwargs: Any) -> Any:
        if not is_admin(user):
            raise_auth_forbidden_error("Admin access required")
        return f(user, *args, **kwargs)

    return decorated  # type: ignore[return-value]
