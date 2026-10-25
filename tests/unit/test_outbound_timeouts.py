"""Every outbound call has an explicit timeout (S5).

Without one a stalled peer holds a gunicorn thread until the worker timeout
(600 s), and the user's turn hangs with it. HTTP calls must pass `timeout=`;
LLM clients must be built with one too.
"""

import ast
from pathlib import Path

_SRC = Path(__file__).parents[2] / "src"
_HTTP_MODULES = {"requests", "httpx"}
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "request", "stream"}
_HTTP_CLIENTS = {"Client", "AsyncClient"}
# LLM clients and the keyword that bounds their requests
_LLM_CLIENTS = {"Client": "http_options", "ChatGoogleGenerativeAI": "timeout"}
# LLM clients allowed without a timeout (none since Oct 25 2026: all use
# GEMINI_REQUEST_TIMEOUT_SECONDS); the list only shrinks
_LLM_BASELINE: set[tuple[str, str]] = set()


def _calls() -> list[tuple[str, str, ast.Call]]:
    """(path relative to src, enclosing function, call) for every call in src/."""
    found = []
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for func in ast.walk(tree):
            if isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
                for node in ast.walk(func):
                    if isinstance(node, ast.Call):
                        found.append((str(path.relative_to(_SRC)), func.name, node))  # noqa: PERF401
    return found


def _keywords(call: ast.Call) -> set[str | None]:
    return {kw.arg for kw in call.keywords}


def test_http_calls_pass_a_timeout() -> None:
    missing = set()
    for path, func, call in _calls():
        target = call.func
        if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)):
            continue
        module, name = target.value.id, target.attr
        is_call = module in _HTTP_MODULES and (name in _HTTP_METHODS or name in _HTTP_CLIENTS)
        # **kwargs may carry it; can't see inside
        if is_call and not _keywords(call) & {"timeout", None}:
            missing.add(f"{path}:{call.lineno} {module}.{name}() in {func}")
    assert missing == set()


def test_llm_clients_are_built_with_a_timeout() -> None:
    unbounded = set()
    for path, func, call in _calls():
        target = call.func
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        keyword = _LLM_CLIENTS.get(name)
        if name == "Client" and not (
            isinstance(target, ast.Attribute) and getattr(target.value, "id", "") == "genai"
        ):
            continue
        if keyword and keyword not in _keywords(call):
            unbounded.add((path, func))
    assert unbounded - _LLM_BASELINE == set(), "pass a timeout to these LLM clients"
    assert _LLM_BASELINE - unbounded == set(), (
        "these have a timeout now: drop them from the baseline"
    )
