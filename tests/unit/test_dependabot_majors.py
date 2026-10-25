"""Dependabot PRs auto-merge only for patch and minor updates (P3).

The auto-merge workflow runs on workflow_run, where Dependabot's metadata
action can't run, so .github/scripts/major_update.py reads the versions
from the PR title and body instead.
"""

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "major_update", Path(__file__).parents[2] / ".github" / "scripts" / "major_update.py"
)
assert _SPEC and _SPEC.loader
major_update = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(major_update)


@pytest.mark.parametrize(
    ("text", "major"),
    [
        ("Bump vite from 8.3.5 to 8.4.0 in /web", False),
        ("Bump ruff from 0.15.1 to 0.15.2", False),
        ("Bump typescript from 6.0.3 to 7.0.0 in /web", True),
        ("Bump katex from 0.18.10 to 0.19.0", True),  # 0.x minor is breaking
        ("Bumps [actions/checkout](https://x) from 6 to 7.", True),
        ("Bumps [actions/checkout](https://x) from v7.1 to v7.2.", False),
        (
            "Bump the python group with 2 updates\n"
            "Updates `httpx` from 0.28.1 to 0.28.2\nUpdates `flask` from 3.1.9 to 4.0.0",
            True,
        ),
        (
            "Bump the python group with 2 updates\n"
            "Updates `httpx` from 0.28.1 to 0.28.2\nUpdates `flask` from 3.1.9 to 3.2.0",
            False,
        ),
    ],
)
def test_classifies_updates(text: str, major: bool) -> None:
    assert major_update.has_major_update(text) is major


def test_unreadable_text_counts_as_major() -> None:
    """Fail closed: no versions found means a person looks at it."""
    assert major_update.has_major_update("Bump something") is True
