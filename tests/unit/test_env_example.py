"""Every setting src/config.py reads is documented in .env.example (P1).

.env.example is the reference both real .env files follow line for line, so a
setting missing from it is invisible to whoever configures the app.
"""

import re
from pathlib import Path

_ROOT = Path(__file__).parents[2]
# Set only by the E2E server; never belongs in a real configuration
_NOT_CONFIGURATION = {"E2E_TESTING"}
# Undocumented settings allowed (none since Oct 25 2026); the list only shrinks
_UNDOCUMENTED_BASELINE: set[str] = set()


def _read_by_config() -> set[str]:
    source = (_ROOT / "src" / "config.py").read_text()
    reads = re.findall(r'os\.(?:getenv|environ\.get)\(\s*"([A-Z0-9_]+)"', source)
    reads += re.findall(r'os\.environ\[\s*"([A-Z0-9_]+)"\s*\]', source)
    return set(reads)


def _documented() -> set[str]:
    example = (_ROOT / ".env.example").read_text()
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", example, re.MULTILINE))


def test_every_setting_is_documented() -> None:
    undocumented = _read_by_config() - _documented() - _NOT_CONFIGURATION
    assert undocumented - _UNDOCUMENTED_BASELINE == set(), "add these to .env.example"


def test_the_baseline_only_shrinks() -> None:
    """A documented (or removed) setting leaves the baseline."""
    stale = _UNDOCUMENTED_BASELINE - (_read_by_config() - _documented())
    assert stale == set(), "remove these from _UNDOCUMENTED_BASELINE"
