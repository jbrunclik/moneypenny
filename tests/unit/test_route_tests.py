"""Rule T8 (backend half): every route module ships with an integration test.

A module in `src/api/routes/` is covered by `tests/integration/test_routes_<name>.py`
or by an integration test that imports it. The frontend half (`core/*.ts`) is
`web/tests/unit/core-tests.test.ts`. The baseline holds the modules without one
when the rule was added (Oct 26 2026); it only shrinks.
"""

import ast
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_ROUTES = _ROOT / "src" / "api" / "routes"
_INTEGRATION = _ROOT / "tests" / "integration"

# Emptied Oct 26 2026 (the tests moved to test_routes_<name>.py); stays empty
_UNTESTED_BASELINE: set[str] = set()


def _imported_route_modules() -> set[str]:
    imported = set()
    for path in _INTEGRATION.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("src.api.routes."):
                    imported.add(node.module.rsplit(".", 1)[1])
                elif node.module == "src.api.routes":
                    imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imported.update(
                    alias.name.rsplit(".", 1)[1]
                    for alias in node.names
                    if alias.name.startswith("src.api.routes.")
                )
    return imported


def _untested() -> set[str]:
    imported = _imported_route_modules()
    return {
        path.stem
        for path in _ROUTES.glob("*.py")
        if path.stem != "__init__"
        and not (_INTEGRATION / f"test_routes_{path.stem}.py").exists()
        and path.stem not in imported
    }


def test_every_route_module_has_a_test() -> None:
    new = _untested() - _UNTESTED_BASELINE
    assert new == set(), "add tests/integration/test_routes_<name>.py"


def test_the_baseline_only_shrinks() -> None:
    stale = _UNTESTED_BASELINE - _untested()
    assert stale == set(), "tested now: delete these from _UNTESTED_BASELINE"
