"""Python functions stay under C1's 100-line maximum (docs/conventions.md).

Ruff has no line-count rule (PLR0915 counts statements), so this measures
what ESLint's `max-lines-per-function` (skipBlankLines, skipComments) does for
the frontend: the lines from `def` to the end of the body, without blank or
comment-only lines - and without the docstring, since a tool's docstring is
its model-facing description and long by design. A nested function counts
toward its parent too, as in ESLint.

Functions over the limit when the check was introduced (Oct 26 2026) are
baselined at their length. The baseline only shrinks: a listed function may
not grow, a new one may not appear, and one that shrinks lowers (or leaves)
its entry in the same commit.
"""

import ast
import io
import tokenize
from pathlib import Path

_ROOT = Path(__file__).parents[2]
# The code vulture checks for dead code: everything but the tests themselves
_SCOPE = [
    *(_ROOT / "src").rglob("*.py"),
    *(_ROOT / "evals").rglob("*.py"),
    *(_ROOT / "scripts").rglob("*.py"),
    *(_ROOT / "tests" / "e2e_server").rglob("*.py"),
    _ROOT / "tests" / "e2e-server.py",
]
MAX_LINES = 100

# "path:Qualified.name" -> current length; only shrinks
BASELINE: dict[str, int] = {
    "src/agent/executor.py:execute_agent": 125,
    "src/api/routes/planner.py:get_planner_dashboard": 120,
    "src/agent/tools/google_calendar.py:google_calendar": 107,
    "src/api/routes/files.py:get_message_file": 103,
}

_NON_CODE_TOKENS = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENDMARKER,
}


def _code_lines(source: str) -> set[int]:
    """Line numbers holding at least one code token (not blank, not only a comment)."""
    lines = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type not in _NON_CODE_TOKENS:
            lines.update(range(token.start[0], token.end[0] + 1))
    blank = {n for n, text in enumerate(source.splitlines(), 1) if not text.strip()}
    return lines - blank


def _docstring_lines(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[int]:
    first = func.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return set(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return set()


def _function_lengths(path: Path) -> dict[str, int]:
    """Qualified name -> counted length, for every function in the file."""
    source = path.read_text()
    code = _code_lines(source)
    lengths: dict[str, int] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                span = set(range(child.lineno, (child.end_lineno or child.lineno) + 1))
                name = prefix + child.name
                lengths[name] = len(span & code - _docstring_lines(child))
                visit(child, name + ".")
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")
            else:
                visit(child, prefix)

    visit(ast.parse(source), "")
    return lengths


def _long_functions() -> dict[str, int]:
    return {
        f"{path.relative_to(_ROOT)}:{name}": length
        for path in sorted(_SCOPE)
        for name, length in _function_lengths(path).items()
        if length > MAX_LINES
    }


def test_functions_stay_under_the_maximum() -> None:
    long = _long_functions()
    new = {key: n for key, n in long.items() if key not in BASELINE}
    grown = {key: n for key, n in long.items() if key in BASELINE and n > BASELINE[key]}
    assert new == {}, f"functions over {MAX_LINES} lines - extract named helpers"
    assert grown == {}, "baselined functions grew - shrink them instead"


def test_baseline_only_shrinks() -> None:
    long = _long_functions()
    stale = {key: long.get(key) for key, n in BASELINE.items() if long.get(key) != n}
    assert stale == {}, "baselined functions shrank or are gone: lower or drop their entries"


def test_counting_skips_docstring_blank_and_comment_lines(tmp_path: Path) -> None:
    path = tmp_path / "sample.py"
    path.write_text(
        "def outer(x):\n"
        '    """Doc\n\n    more doc.\n    """\n'
        "    # a comment\n"
        "\n"
        "    def inner():\n"
        "        return x  # trailing comment\n"
        "    return inner\n"
    )
    assert _function_lengths(path) == {"outer": 4, "outer.inner": 2}
