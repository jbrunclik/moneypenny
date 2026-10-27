"""Rule B6: the number of `Any` uses in src/ only goes down.

mypy strict accepts `Any`, so a dict-shaped value typed `dict[str, Any]`
passes it while checking nothing. New code gives such values a TypedDict,
dataclass or Pydantic model (docs/conventions.md "Typing"). Counted: every
`Any` / `typing.Any` reference except the import itself. When the count
drops, lower the baseline in the same commit.
"""

import ast
from pathlib import Path

_SRC = Path(__file__).parents[2] / "src"

ANY_BASELINE = 1068  # Oct 27 2026 (file attachments and message payloads typed)


def _any_uses(path: Path) -> int:
    return sum(
        1
        for node in ast.walk(ast.parse(path.read_text()))
        if (isinstance(node, ast.Name) and node.id == "Any")
        or (
            isinstance(node, ast.Attribute)
            and node.attr == "Any"
            and isinstance(node.value, ast.Name)
            and node.value.id == "typing"
        )
    )


def test_any_count_only_shrinks() -> None:
    count = sum(_any_uses(path) for path in _SRC.rglob("*.py"))
    assert count <= ANY_BASELINE, f"{count} Any uses (baseline {ANY_BASELINE}) - type it instead"
    assert count == ANY_BASELINE, f"Any uses dropped to {count}: lower ANY_BASELINE to {count}"
