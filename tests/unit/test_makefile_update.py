"""`make update` backs up the databases before any new code reaches the checkout.

Timers run from the same checkout, so once the pull lands the new code is
live for them. The backup has to exist before that, and a failed backup must
stop the deploy before it changes anything.
"""

import re
from pathlib import Path

MAKEFILE = Path(__file__).parent.parent.parent / "Makefile"

# Recipe lines that put other code in the working tree
_CODE_CHANGING = re.compile(r"\bgit (pull|merge|checkout -q|rebase|reset)\b")


def _recipe(target: str) -> list[str]:
    lines = MAKEFILE.read_text().splitlines()
    start = lines.index(f"{target}:") + 1
    recipe = []
    for line in lines[start:]:
        if not line.startswith("\t"):
            break
        stripped = line.strip()
        if not stripped.startswith("#"):
            recipe.append(stripped)
    return recipe


def test_update_backs_up_before_changing_code() -> None:
    recipe = _recipe("_update")
    backup = next(i for i, line in enumerate(recipe) if "backup_databases.py" in line)
    first_change = next(i for i, line in enumerate(recipe) if _CODE_CHANGING.search(line))

    assert backup < first_change, recipe


def test_update_aborts_when_the_backup_fails() -> None:
    backup_line = next(line for line in _recipe("_update") if "backup_databases.py" in line)

    assert "exit 1" in backup_line


def test_update_keeps_the_health_gate() -> None:
    assert any("_build_and_reload" in line for line in _recipe("_update"))
    assert any("deploy_health_gate.py" in line for line in _recipe("_build_and_reload"))
