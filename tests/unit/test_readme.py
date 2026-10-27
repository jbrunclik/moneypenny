"""The README is the project's front page: what it states about the app must be true.

It drifted before - it named a Gemini model the app no longer used - so the
facts a test can check are checked: every configured model by name, and every
screenshot it shows exists (they are visual-test baselines).
"""

import re
from pathlib import Path

from src.config import Config

_ROOT = Path(__file__).parents[2]
_README = (_ROOT / "README.md").read_text()


def test_names_every_configured_model() -> None:
    missing = [
        f"{model['name']} ({model['short_name']})"
        for model in Config.MODELS.values()
        if model["name"] not in _README or f'"{model["short_name"]}"' not in _README
    ]
    assert missing == [], f"README.md does not describe these models: {missing}"


def test_its_images_exist() -> None:
    images = re.findall(r'<img src="([^"]+)"', _README)
    assert images, "the README shows no screenshots"
    missing = [path for path in images if not (_ROOT / path).is_file()]
    assert missing == [], f"README.md shows missing images: {missing}"


def test_the_checks_see_a_drift() -> None:
    """A model the README doesn't name fails the model check (T12)."""
    stale = _README.replace(next(iter(Config.MODELS.values()))["name"], "Gemini 0.0")
    named = all(model["name"] in stale for model in Config.MODELS.values())
    assert not named
