"""Admin access (S12): the accounts listed in ADMIN_EMAILS."""

from collections.abc import Callable
from functools import wraps
from typing import Any

from src.api.errors import raise_auth_forbidden_error, raise_validation_error
from src.db.models import User
from src.utils.model_access import is_admin_email, model_allowed


def is_admin(user: User) -> bool:
    """Whether the user may see the admin page."""
    return is_admin_email(user.email)


def check_model_allowed(user: User, model: str) -> None:
    """400 when the account may not pick the model (Config.ADMIN_ONLY_MODELS).
    Unknown model ids are the request schema's to refuse."""
    if not model_allowed(user.email, model):
        raise_validation_error("That model is not available on this account.", field="model")


def require_admin[F: Callable[..., Any]](f: F) -> F:
    """Refuse non-admins with 403. Goes inside @require_auth, which injects the user."""

    @wraps(f)
    def decorated(user: User, *args: Any, **kwargs: Any) -> Any:
        if not is_admin(user):
            raise_auth_forbidden_error("Admin access required")
        return f(user, *args, **kwargs)

    return decorated  # type: ignore[return-value]
