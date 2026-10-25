"""Logs identify users by id and never carry secrets or whole texts (S8).

docs/conventions.md "Logging and privacy": truncated excerpts that help
improve the agent are fine; emails, credentials and full message texts or
histories are not. This checks the field names passed in `extra=`.
"""

import ast
from pathlib import Path

_SRC = Path(__file__).parents[2] / "src"
_LEVELS = {"debug", "info", "warning", "error", "exception", "critical"}
_DENIED = {
    "email",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "secret",
    "authorization",
    "cookie",
    "content",
    "text",
    "message_text",
    "history",
    "messages",
}
_DENIED_SUFFIXES = ("_email", "_password", "_secret", "_api_key", "_access_token")


def _logged_keys() -> list[tuple[str, int, str]]:
    found = []
    for path in sorted(_SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _LEVELS
            ):
                continue
            for keyword in node.keywords:
                if keyword.arg == "extra" and isinstance(keyword.value, ast.Dict):
                    found.extend(
                        (str(path.relative_to(_SRC)), node.lineno, key.value)
                        for key in keyword.value.keys
                        if isinstance(key, ast.Constant) and isinstance(key.value, str)
                    )
    return found


def test_no_personal_or_secret_fields_in_logs() -> None:
    offending = [
        f"{path}:{line} {key}"
        for path, line, key in _logged_keys()
        if key.lower() in _DENIED or key.lower().endswith(_DENIED_SUFFIXES)
    ]
    assert offending == [], "log user_id, a truncated excerpt or a length instead"


def test_the_scan_sees_log_calls() -> None:
    """Guards the scan itself: it must find the user_id fields that are everywhere."""
    assert sum(1 for _, _, key in _logged_keys() if key == "user_id") > 100
