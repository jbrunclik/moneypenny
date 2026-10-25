"""The migrations form one chain, and every step can be undone or says why not (P2).

Migrations apply at startup on every worker. Two parallel sessions that both
add `0069_...` depending on `0068_...` fork the chain, and the next deploy
applies them in an order nobody tested. Migrations up to 0021 predate
__depends__ and run in filename order.
"""

import ast
import itertools
import re
from pathlib import Path

import pytest

_DIR = Path(__file__).parents[2] / "migrations"
_FIRST_CHAINED = "0022"
# Two migrations shipped as 0021 before this check existed (the list only shrinks)
_DUPLICATE_PREFIX_BASELINE = {"0021"}
# Applied everywhere before this check existed; they hold one-way backfills
_NO_ROLLBACK_BASELINE = {
    "0015_add_full_text_search",
    "0020_add_planner_support",
    "0024_add_autonomous_agents",
    "0030_archive_conversations",
    "0039_add_agent_system_type",
    "0062_add_conversation_read_count",
}


def _migrations() -> dict[str, list[str]]:
    """Migration id -> the ids it depends on."""
    deps: dict[str, list[str]] = {}
    for path in sorted(_DIR.iterdir()):
        text = path.read_text() if path.suffix in {".py", ".sql"} else ""
        if path.suffix == ".py":
            match = re.search(r"__depends__\s*=\s*\{([^}]*)\}", text)
            deps[path.stem] = re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)) if match else []
        elif path.suffix == ".sql":
            lines = re.findall(r"--\s*depends:\s*(.+)", text)
            deps[path.stem] = [name for line in lines for name in line.split()]
    return deps


def test_migration_numbers_are_unique() -> None:
    prefixes = [name[:4] for name in _migrations()]
    duplicates = {p for p in prefixes if prefixes.count(p) > 1} - _DUPLICATE_PREFIX_BASELINE
    assert duplicates == set(), f"two migrations share a number: {sorted(duplicates)}"


def test_each_migration_depends_on_the_one_before() -> None:
    migrations = _migrations()
    names = sorted(migrations)
    broken = [
        f"{name} depends on {migrations[name]}, expected [{previous!r}]"
        for previous, name in itertools.pairwise(names)
        if name[:4] >= _FIRST_CHAINED and migrations[name] != [previous]
    ]
    assert broken == []


@pytest.mark.parametrize(
    "path",
    [p for p in sorted(_DIR.glob("*.py")) if p.stem not in _NO_ROLLBACK_BASELINE],
    ids=lambda p: p.stem,
)
def test_every_step_has_a_rollback_or_says_why_not(path: Path) -> None:
    source = path.read_text()
    tree = ast.parse(source)
    one_way = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "step"
        and (
            len(node.args) < 2
            or (isinstance(node.args[1], ast.Constant) and node.args[1].value is None)
        )
    ]
    if one_way:
        assert "# irreversible:" in source, (
            f"{path.name}: step at line {one_way} has no rollback - add one, or a "
            "'# irreversible: <reason>' comment"
        )
