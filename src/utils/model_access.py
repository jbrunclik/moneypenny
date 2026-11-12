"""Which chat models an account may use (Config.ADMIN_ONLY_MODELS).

Admin-only models are left out of the model list, refused when a chat or job
is saved with one, and a chat or job that still stores one runs on
DEFAULT_MODEL. Background jobs that name a model in config (the deep-research
writer, memory defrag, the eval judge) are not account-bound and unaffected.
"""

from src.config import Config


def is_admin_email(email: str) -> bool:
    """Whether the address is in ADMIN_EMAILS (case-insensitive)."""
    return email.lower() in {admin.lower() for admin in Config.ADMIN_EMAILS}


def model_allowed(email: str, model: str) -> bool:
    """Whether the account may pick the model for a chat or job."""
    if model not in Config.MODELS:
        return False
    return model not in Config.ADMIN_ONLY_MODELS or is_admin_email(email)


def models_for(email: str) -> list[str]:
    """The MODELS the account may pick, in MODELS order."""
    return [model for model in Config.MODELS if model_allowed(email, model)]


def model_for(email: str, model: str | None) -> str:
    """The model a turn or run uses: the stored one, unless it is admin-only
    and the account is not an admin (then DEFAULT_MODEL)."""
    if not model or (model in Config.ADMIN_ONLY_MODELS and not is_admin_email(email)):
        return Config.DEFAULT_MODEL
    return model
