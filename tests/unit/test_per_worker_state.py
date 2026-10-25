"""Rule B7: module-level mutable state says why it is safe per worker.

Production runs several gunicorn workers, so a module-level dict or singleton
holds one copy per process: state set by one request is invisible to the next
request if it lands on another worker (the Garmin MFA bug). Each such name
carries a `# per-worker: <why safe>` comment on its line or in the comment
block right above it - or the state moves to the database / kv_store.

Detected: lowercase module-level names bound to a mutable container or a Lazy
singleton, and any module-level name a function rebinds with `global`.
UPPERCASE containers are constants by convention and not checked here.
"""

import ast
from collections.abc import Sequence
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
MARKER = "# per-worker:"
_MUTABLE_CALLS = {
    "dict",
    "list",
    "set",
    "OrderedDict",
    "defaultdict",
    "deque",
    "Counter",
    "WeakValueDictionary",
    "WeakKeyDictionary",
    "WeakSet",
    "Lazy",
}
_MUTABLE_LITERALS = (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)


def _is_mutable(value: ast.expr | None) -> bool:
    if isinstance(value, _MUTABLE_LITERALS):
        return True
    if isinstance(value, ast.Call):
        func = value.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        return name in _MUTABLE_CALLS
    return False


def _module_bindings(tree: ast.Module) -> list[tuple[str, int, ast.expr | None]]:
    bindings: list[tuple[str, int, ast.expr | None]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            bindings += [
                (t.id, node.lineno, node.value) for t in node.targets if isinstance(t, ast.Name)
            ]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bindings.append((node.target.id, node.lineno, node.value))
    return bindings


def _is_declared(lines: Sequence[str], lineno: int) -> bool:
    """The marker sits on the binding's line or in the comment block above it."""
    if MARKER in lines[lineno - 1]:
        return True
    index = lineno - 2
    while index >= 0 and lines[index].lstrip().startswith("#"):
        if MARKER in lines[index]:
            return True
        index -= 1
    return False


def _undeclared_state(source: str) -> list[tuple[str, int]]:
    """(name, line) of each undeclared piece of module-level mutable state."""
    tree = ast.parse(source)
    rebound = {
        name for node in ast.walk(tree) if isinstance(node, ast.Global) for name in node.names
    }
    lines = source.splitlines()
    return [
        (name, lineno)
        for name, lineno, value in _module_bindings(tree)
        if not name.startswith("__")
        and (name in rebound or (not name.isupper() and _is_mutable(value)))
        and not _is_declared(lines, lineno)
    ]


def test_module_level_mutable_state_is_declared_per_worker() -> None:
    undeclared = [
        f"{path.relative_to(SRC.parent)}:{lineno} {name}"
        for path in sorted(SRC.rglob("*.py"))
        for name, lineno in _undeclared_state(path.read_text())
    ]
    assert not undeclared, (
        f"Module-level mutable state without a '{MARKER} <why safe>' comment "
        "(or move it to the DB/kv_store; see docs/conventions.md#multi-worker-state):\n"
        + "\n".join(undeclared)
    )


def test_the_check_flags_undeclared_state_only() -> None:
    source = (
        "# per-worker: a cache, rebuilt on a miss\n"
        "_cache: dict[str, int] = {}\n"
        "_client = Lazy(make_client)  # per-worker: a stateless client\n"
        "_pending = []\n"
        "_lazy = Lazy(make_client)\n"
        "LABELS = {}\n"
        "_flag = None\n"
        "\n"
        "def f() -> None:\n"
        "    global _flag\n"
        "    _flag = True\n"
    )
    assert [name for name, _ in _undeclared_state(source)] == ["_pending", "_lazy", "_flag"]
