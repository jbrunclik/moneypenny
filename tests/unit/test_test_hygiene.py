"""Test-suite hygiene rules (T3, T4, T7 in docs/conventions.md).

Counted rules carry a baseline from when they were introduced (Oct 25 2026).
The count may never grow; when it drops, lower the baseline in the same
commit, so it only shrinks.
"""

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_PY_TESTS = sorted((_ROOT / "tests").rglob("*.py"))
_TS_TESTS = sorted((_ROOT / "web" / "tests").rglob("*.ts"))

SLEEP_BASELINE = 64
WAIT_FOR_TIMEOUT_BASELINE = 284
PRIVATE_IMPORT_BASELINE = 20


def _trees() -> list[tuple[Path, ast.Module]]:
    return [(path, ast.parse(path.read_text())) for path in _PY_TESTS]


def _assert_baseline(count: int, baseline: int, what: str) -> None:
    assert count <= baseline, f"{count} {what} (baseline {baseline}) - don't add new ones"
    assert count == baseline, f"{what} dropped to {count}: lower the baseline to {count}"


def test_no_placeholder_tests() -> None:
    """T3: a test whose body is only pass, a docstring or comments tests nothing."""
    placeholders = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                body = [
                    stmt
                    for stmt in node.body
                    if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
                ]
                if all(isinstance(stmt, ast.Pass) for stmt in body):
                    placeholders.append(f"{path.relative_to(_ROOT)}:{node.lineno} {node.name}")
    assert placeholders == []


def test_fixed_sleeps_say_why() -> None:
    """T4: a fixed sleep needs a same-line comment saying why polling won't do."""
    python = sum(
        1
        for path in _PY_TESTS
        for line in path.read_text().splitlines()
        if re.search(r"\btime\.sleep\(", line) and "#" not in line.split("time.sleep", 1)[1]
    )
    playwright = sum(
        1
        for path in _TS_TESTS
        for line in path.read_text().splitlines()
        if "waitForTimeout(" in line and "//" not in line.split("waitForTimeout(", 1)[1]
    )
    _assert_baseline(python, SLEEP_BASELINE, "uncommented time.sleep calls in tests/")
    _assert_baseline(
        playwright, WAIT_FOR_TIMEOUT_BASELINE, "uncommented waitForTimeout calls in web/tests/"
    )


def test_tests_use_public_names() -> None:
    """T7: importing a module's _private name couples the test to its internals."""
    count = sum(
        1
        for _, tree in _trees()
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("src")
        for alias in node.names
        if alias.name.startswith("_") and not alias.name.startswith("__")
    )
    _assert_baseline(count, PRIVATE_IMPORT_BASELINE, "imports of _private names from src")
