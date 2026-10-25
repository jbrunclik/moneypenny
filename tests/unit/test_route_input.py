"""Rule B4: routes take input through one mechanism.

A JSON body goes through @validate_request and a query string through
@validate_query (src/api/validation.py), so every input is checked by a
schema, fails with the standard 400 and appears in the OpenAPI spec. Reading
request.args, request.json/get_json(), request.form or request.values in a
route bypasses all three.
"""

import ast
from pathlib import Path

ROUTES = Path(__file__).resolve().parents[2] / "src" / "api" / "routes"
_RAW_INPUTS = {"args", "json", "get_json", "form", "values"}


def _raw_reads(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    return [
        f"{path.name}:{node.lineno} request.{node.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr in _RAW_INPUTS
        and isinstance(node.value, ast.Name)
        and node.value.id == "request"
    ]


def test_routes_never_read_raw_input() -> None:
    reads = [read for path in sorted(ROUTES.rglob("*.py")) for read in _raw_reads(path)]
    assert not reads, f"use @validate_request / @validate_query instead: {reads}"


def test_the_guard_catches_a_raw_read(tmp_path: Path) -> None:
    route = tmp_path / "route.py"
    route.write_text("from flask import request\nlimit = request.args.get('limit')\n")
    assert _raw_reads(route) == ["route.py:2 request.args"]
