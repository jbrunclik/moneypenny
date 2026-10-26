"""Rule B2: src/ never imports another module's `_private` names.

An underscore says "only this module uses me"; importing it elsewhere couples
the two modules behind that promise. Make the name public, or move it to the
module both need. Checked: `from x import _name` and `module._name` on a
module imported with `import`. The test side of the rule is T7 in
test_test_hygiene.py (tests importing `_private` names from src).

The baseline only shrinks: fixed one? Delete its entry.
"""

import ast
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_SRC = _ROOT / "src"

_BASELINE = {
    # Third-party: documents @validate_request bodies the way APIFlask's @api.input does
    "src/api/validation.py: apiflask.scaffold._annotate",
}


def _is_private(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")


def _private_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    where = path.relative_to(_ROOT)
    found = set()
    modules = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            found.update(
                f"{where}: {module}.{alias.name}" for alias in node.names if _is_private(alias.name)
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules[alias.asname or alias.name.split(".")[0]] = alias.asname or alias.name
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and _is_private(node.attr)):
            continue
        dotted = ast.unparse(node.value)
        if dotted.split(".")[0] in modules and dotted.startswith(tuple(modules.values())):
            found.add(f"{where}: {dotted}.{node.attr}")
    return found


def _all_private_imports() -> set[str]:
    return {entry for path in sorted(_SRC.rglob("*.py")) for entry in _private_imports(path)}


def test_no_new_private_imports() -> None:
    new = _all_private_imports() - _BASELINE
    assert new == set(), "make the name public (or move it) instead of importing a _private one"


def test_the_baseline_only_shrinks() -> None:
    stale = _BASELINE - _all_private_imports()
    assert stale == set(), "fixed: delete these from _BASELINE"
