"""Every setting src/config.py reads is documented in .env.example (P1).

.env.example is the reference both real .env files follow line for line, so a
setting missing from it is invisible to whoever configures the app.
"""

import re
from pathlib import Path

_ROOT = Path(__file__).parents[2]
# Set only by the E2E server; never belongs in a real configuration
_NOT_CONFIGURATION = {"E2E_TESTING"}
# Undocumented before this check existed. Documenting them means realigning both
# .env files, so it is its own TODO item; the list only shrinks.
_UNDOCUMENTED_BASELINE = {
    "AGENT_AGED_TOOL_RESULT_MAX_CHARS",
    "AGENT_GRAPH_CACHE_SIZE",
    "AGENT_MAX_TOOL_RETRIES",
    "AGENT_TOOL_ROUNDS_SOFT_NUDGE",
    "BLOB_STORAGE_PATH",
    "CODE_EXECUTION_MAX_STDOUT_CHARS",
    "CONVERSATIONS_DEFAULT_PAGE_SIZE",
    "CONVERSATIONS_MAX_PAGE_SIZE",
    "CONVERSATION_READ_MAX_CHARS_PER_MESSAGE",
    "CONVERSATION_READ_MAX_MESSAGES",
    "CONVERSATION_SEARCH_MAX_RESULTS",
    "DASHBOARD_CACHE_TTL_SECONDS",
    "EVAL_JUDGE_MODEL",
    "FETCH_URL_MAX_FILE_SIZE",
    "MAX_REQUEST_SIZE",
    "MEMORY_INJECT_FULL_MAX",
    "MEMORY_INJECT_RECENT_COUNT",
    "MEMORY_SEARCH_MIN_SIMILARITY",
    "MESSAGES_AROUND_AFTER_DEFAULT",
    "MESSAGES_AROUND_BEFORE_DEFAULT",
    "MESSAGES_DEFAULT_PAGE_SIZE",
    "MESSAGES_MAX_PAGE_SIZE",
    "PROGRAM_KV_INJECTION_MAX_CHARS",
    "RATE_LIMITING_ENABLED",
    "RATE_LIMIT_AUTH",
    "RATE_LIMIT_CHAT",
    "RATE_LIMIT_CONVERSATIONS",
    "RATE_LIMIT_DEFAULT",
    "RATE_LIMIT_FILES",
    "RATE_LIMIT_STORAGE_URI",
    "SEARCH_DEFAULT_LIMIT",
    "SEARCH_MAX_LIMIT",
    "SEARCH_MAX_QUERY_LENGTH",
    "STREAM_JOURNAL_ENABLED",
    "STREAM_JOURNAL_FLUSH_EVENTS",
    "STREAM_JOURNAL_FLUSH_INTERVAL_SECONDS",
    "STREAM_JOURNAL_TTL_SECONDS",
    "STREAM_RESUME_SAVE_GRACE_SECONDS",
    "STREAM_RESUME_STALL_SECONDS",
    "THUMBNAIL_RESAMPLING",
    "THUMBNAIL_SKIP_THRESHOLD",
    "THUMBNAIL_STALE_THRESHOLD",
    "THUMBNAIL_WORKER_THREADS",
    "TODOIST_MAX_TASK_RESULTS",
    "TOOL_RESULTS_CLEANUP_INTERVAL_SECONDS",
    "TOOL_RESULTS_TTL_SECONDS",
}


def _read_by_config() -> set[str]:
    source = (_ROOT / "src" / "config.py").read_text()
    reads = re.findall(r'os\.(?:getenv|environ\.get)\(\s*"([A-Z0-9_]+)"', source)
    reads += re.findall(r'os\.environ\[\s*"([A-Z0-9_]+)"\s*\]', source)
    return set(reads)


def _documented() -> set[str]:
    example = (_ROOT / ".env.example").read_text()
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", example, re.MULTILINE))


def test_every_setting_is_documented() -> None:
    undocumented = _read_by_config() - _documented() - _NOT_CONFIGURATION
    assert undocumented - _UNDOCUMENTED_BASELINE == set(), "add these to .env.example"


def test_the_baseline_only_shrinks() -> None:
    """A documented (or removed) setting leaves the baseline."""
    stale = _UNDOCUMENTED_BASELINE - (_read_by_config() - _documented())
    assert stale == set(), "remove these from _UNDOCUMENTED_BASELINE"
