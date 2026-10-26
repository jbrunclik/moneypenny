"""Rule B11: env vars are read only in src/config.py; settings carry their unit.

A setting read somewhere else escapes `.env.example` (P1), its default and its
docs. A time or size setting without its unit (`CHAT_TIMEOUT`) leaves every
reader guessing whether 600 means seconds or milliseconds.

The unit check covers `Config` attributes whose name says they hold a
duration (TIMEOUT, INTERVAL, DELAY, TTL...) or a size in bytes (SIZE). A
character or word count (`..._LENGTH`, `..._MAX_WORDS`) is a count, not a
unit-bearing setting, and is not checked. The baseline holds the names that
predate the rule (Oct 26 2026): every one of them is an env var set in the
real `.env` files, so renaming one means renaming it there in the same
deploy. It only shrinks.
"""

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_SRC = _ROOT / "src"
_CONFIG = _SRC / "config.py"

_DURATION_OR_SIZE = re.compile(
    r"TIMEOUT|INTERVAL|DELAY|TTL|DURATION|PERIOD|BACKOFF|COOLDOWN|GRACE|STALL|WAIT|_AGE\b|SIZE"
)
_UNIT = re.compile(r"_(MS|SECONDS|MINUTES|HOURS|DAYS|WEEKS|MONTHS|BYTES|KB|MB|PX)$")
# Names the pattern matches that hold no duration or byte size
_NOT_A_UNIT_SETTING = {
    "AGENT_GRAPH_CACHE_SIZE",  # cache entries
    "CONVERSATIONS_DEFAULT_PAGE_SIZE",  # rows per page
    "CONVERSATIONS_MAX_PAGE_SIZE",
    "MESSAGES_DEFAULT_PAGE_SIZE",
    "MESSAGES_MAX_PAGE_SIZE",
    "SYNC_CHANGES_PAGE_SIZE",
    "THUMBNAIL_MAX_SIZE",  # a (width, height) tuple in pixels
}
# Unit-less settings from before the rule; only shrinks
_NO_UNIT_BASELINE = {
    "CHAT_TIMEOUT",
    "CODE_SANDBOX_TIMEOUT",
    "FETCH_URL_MAX_FILE_SIZE",
    "GARMIN_API_TIMEOUT",
    "GOOGLE_AUTH_TIMEOUT",
    "GOOGLE_CALENDAR_API_TIMEOUT",
    "GUNICORN_TIMEOUT",
    "MAPY_API_TIMEOUT",
    "MAX_FILE_SIZE",
    "MAX_REQUEST_SIZE",
    "MAX_VIDEO_FILE_SIZE",
    "PUSH_SEND_TIMEOUT",
    "ROUVY_HTTP_TIMEOUT",
    "SSE_KEEPALIVE_INTERVAL",
    "STREAM_CLEANUP_THREAD_TIMEOUT",
    "STREAM_CLEANUP_WAIT_DELAY",
    "TODOIST_API_TIMEOUT",
    "TOOL_TIMEOUT",
    "WEATHER_API_TIMEOUT",
    "WHATSAPP_API_TIMEOUT",
}


def _env_reads(path: Path) -> list[str]:
    """`os.getenv`, `os.environ` and a bare `getenv`/`environ` imported from os."""
    tree = ast.parse(path.read_text())
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "os"
        for alias in node.names
        if alias.name in {"getenv", "environ"}
    }
    reads = []
    for node in ast.walk(tree):
        is_os_attr = (
            isinstance(node, ast.Attribute)
            and node.attr in {"getenv", "environ"}
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        )
        if is_os_attr or (isinstance(node, ast.Name) and node.id in imported):
            reads.append(f"{path.relative_to(_ROOT)}:{node.lineno}")
    return reads


def _unitless_settings() -> set[str]:
    tree = ast.parse(_CONFIG.read_text())
    config = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Config")
    names = set()
    for stmt in config.body:
        target = stmt.target if isinstance(stmt, ast.AnnAssign) else None
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
        if isinstance(target, ast.Name) and target.id.isupper():
            names.add(target.id)
    return {
        name
        for name in names
        if _DURATION_OR_SIZE.search(name)
        and not _UNIT.search(name)
        and name not in _NOT_A_UNIT_SETTING
    }


def test_env_vars_are_read_only_in_config() -> None:
    reads = [
        read for path in sorted(_SRC.rglob("*.py")) if path != _CONFIG for read in _env_reads(path)
    ]
    assert reads == [], "read the setting through Config (src/config.py) instead"


def test_new_time_and_size_settings_carry_their_unit() -> None:
    new = _unitless_settings() - _NO_UNIT_BASELINE
    assert new == set(), "name the unit: _SECONDS, _MS, _BYTES, _DAYS..."


def test_the_unit_baseline_only_shrinks() -> None:
    stale = _NO_UNIT_BASELINE - _unitless_settings()
    assert stale == set(), "renamed or removed: delete these from _NO_UNIT_BASELINE"
