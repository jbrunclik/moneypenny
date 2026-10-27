"""Rule B12: datetimes are aware - instants in UTC, days in APP_TIMEZONE.

ruff DTZ catches naive constructors (`datetime.now()`, `date.today()`,
`datetime(...)` without tzinfo). This scan catches what it can't see: calls
that parse or convert through the process timezone or drop the zone -

- `datetime.fromisoformat` / `datetime.strptime`: a value without an offset
  parses naive; stored values go through `timestamps.from_db` (a parse
  followed at once by `.replace(tzinfo=<zone>)` is fine);
- `datetime.combine` without `tzinfo=`;
- `.astimezone()` without a zone, `time.localtime` / `time.strftime` /
  `time.mktime`: the HOST zone, which is not the household's (`to_local`);
- `.replace(tzinfo=None)`: makes a naive value.

`src/db/models/timestamps.py` reads and writes the legacy naive formats and is
exempt. Elsewhere a deliberate use carries `# tz-naive: <why>` on its line or
the line above.
"""

import ast
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_SCANNED = ("src", "scripts", "evals")
_EXEMPT = {_ROOT / "src" / "db" / "models" / "timestamps.py"}
_MARKER = "# tz-naive:"

_DATETIME_PARSERS = {"fromisoformat", "strptime"}
_HOST_ZONE_TIME_CALLS = {"localtime", "strftime", "mktime"}


def _is_name(node: ast.expr, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _violation(call: ast.Call) -> str | None:
    func = call.func
    if not isinstance(func, ast.Attribute):
        return None
    if _is_name(func.value, "datetime") and func.attr in _DATETIME_PARSERS:
        return f"datetime.{func.attr}"
    if (
        _is_name(func.value, "datetime")
        and func.attr == "combine"
        and not any(k.arg == "tzinfo" for k in call.keywords)
        and len(call.args) < 3
    ):
        return "datetime.combine without tzinfo"
    if _is_name(func.value, "time") and func.attr in _HOST_ZONE_TIME_CALLS:
        return f"time.{func.attr}"
    if func.attr == "astimezone" and not call.args and not call.keywords:
        return ".astimezone() without a zone"
    if func.attr == "replace" and any(
        k.arg == "tzinfo" and isinstance(k.value, ast.Constant) and k.value.value is None
        for k in call.keywords
    ):
        return ".replace(tzinfo=None)"
    return None


def _zoned_at_once(tree: ast.AST) -> set[int]:
    """ids of calls whose result gets `.replace(tzinfo=<a zone>)` right away."""
    return {
        id(node.func.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "replace"
        and any(
            k.arg == "tzinfo" and not (isinstance(k.value, ast.Constant) and k.value.value is None)
            for k in node.keywords
        )
    }


def _naive_calls(path: Path) -> list[str]:
    source = path.read_text()
    lines = source.splitlines()
    tree = ast.parse(source)
    zoned = _zoned_at_once(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or id(node) in zoned:
            continue
        what = _violation(node)
        if what is None:
            continue
        here = lines[node.lineno - 1]
        above = lines[node.lineno - 2] if node.lineno > 1 else ""
        if _MARKER in here or _MARKER in above:
            continue
        found.append(f"{path.relative_to(_ROOT)}:{node.lineno}: {what}")
    return found


def test_no_naive_datetime_calls() -> None:
    found = [
        hit
        for top in _SCANNED
        for path in sorted((_ROOT / top).rglob("*.py"))
        if path not in _EXEMPT
        for hit in _naive_calls(path)
    ]
    assert found == [], (
        "naive datetime calls (B12) - use src/utils/clock.py or timestamps.from_db, "
        "or mark a deliberate one '# tz-naive: <why>':\n" + "\n".join(found)
    )


def test_the_scan_sees_each_pattern() -> None:
    """Each banned shape is caught, and the marker lets one through."""
    source = """
from datetime import datetime
import time
datetime.fromisoformat("2026-01-01")
datetime.strptime("x", "%Y")
datetime.combine(d, t)
time.strftime("%Y")
moment.astimezone()
moment.replace(tzinfo=None)
datetime.combine(d, t, tzinfo=zone)
moment.astimezone(zone)
datetime.strptime("x", "%Y").replace(tzinfo=UTC)
# tz-naive: a deliberate one
datetime.fromisoformat("2026-01-01")
"""
    tree = ast.parse(source)
    zoned = _zoned_at_once(tree)
    hits = [
        _violation(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and node.lineno != 14 and id(node) not in zoned
    ]
    assert sorted(h for h in hits if h) == sorted(
        [
            "datetime.fromisoformat",
            "datetime.strptime",
            "datetime.combine without tzinfo",
            "time.strftime",
            ".astimezone() without a zone",
            ".replace(tzinfo=None)",
        ]
    )
