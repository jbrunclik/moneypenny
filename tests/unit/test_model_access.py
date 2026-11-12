"""Admin-only models (Config.ADMIN_ONLY_MODELS, src/utils/model_access.py)."""

from unittest.mock import patch

import pytest

from src.config import Config
from src.utils.model_access import model_allowed, model_for, models_for

_ADMIN = "admin@example.com"
_FAMILY = "kid@example.com"


@pytest.fixture(autouse=True)
def _one_admin():
    with (
        patch.object(Config, "ADMIN_EMAILS", ["Admin@Example.com"]),
        patch.object(Config, "ADMIN_ONLY_MODELS", frozenset({"gemini-4-carbon"})),
    ):
        yield


def test_admins_may_use_every_model() -> None:
    assert models_for(_ADMIN) == list(Config.MODELS)
    assert model_allowed(_ADMIN, "gemini-4-carbon")


def test_the_family_gets_the_rest() -> None:
    assert "gemini-4-carbon" not in models_for(_FAMILY)
    assert Config.DEFAULT_MODEL in models_for(_FAMILY)
    assert not model_allowed(_FAMILY, "gemini-4-carbon")


def test_unknown_models_are_never_allowed() -> None:
    assert not model_allowed(_ADMIN, "gemini-0-nonexistent")


def test_a_stored_admin_only_model_runs_on_the_default_for_the_family() -> None:
    assert model_for(_FAMILY, "gemini-4-carbon") == Config.DEFAULT_MODEL
    assert model_for(_ADMIN, "gemini-4-carbon") == "gemini-4-carbon"


def test_other_stored_models_run_as_stored() -> None:
    assert model_for(_FAMILY, "gemini-4-hydrogen") == "gemini-4-hydrogen"
    assert model_for(_FAMILY, None) == Config.DEFAULT_MODEL
