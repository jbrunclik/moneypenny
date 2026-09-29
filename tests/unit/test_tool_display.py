"""Tests for tool display metadata and detail extraction.

Every tool the model can call must have a TOOL_METADATA entry: without one the
thinking trace falls back to a raw "Used <function_name>" pill. A Sep 2026
audit found three of the five most-called tools (garmin_connect, kv_store,
cite_sources) in exactly that state.
"""

import re
from pathlib import Path
from unittest.mock import patch

from src.agent.tool_display import (
    _CONDITIONAL_TOOLS,
    TOOL_METADATA,
    _format_calendar_detail,
    _format_memory_detail,
    _format_todoist_detail,
    extract_tool_detail,
)
from src.agent.tool_display import extract_tool_detail as _extract_tool_detail
from src.agent.tools import get_all_tool_names, get_available_tools


class TestMetadataCoverage:
    def test_every_bindable_tool_has_display_metadata(self) -> None:
        """Config-dependent by design: only tools this env can bind must be labelled."""
        bindable = {tool.name for tool in get_available_tools()} | set(_CONDITIONAL_TOOLS)
        missing = sorted(bindable - set(TOOL_METADATA))
        assert not missing, f"tools would render as raw function names: {missing}"

    def test_no_metadata_for_tools_that_do_not_exist(self) -> None:
        """Must NOT use get_available_tools(): integration tools disappear from it
        when credentials are absent, so comparing against it passes on a
        configured laptop and fails in CI (which is exactly what happened)."""
        unknown = sorted(set(TOOL_METADATA) - get_all_tool_names())
        assert not unknown, f"metadata for tools that do not exist: {unknown}"

    def test_metadata_covers_every_tool_that_exists(self) -> None:
        """Stronger than the bindable check and config-independent: no tool
        anywhere in the registry may be missing a label, even one this
        environment cannot currently bind."""
        missing = sorted(get_all_tool_names() - set(TOOL_METADATA))
        assert not missing, f"tools with no TOOL_METADATA entry: {missing}"

    def test_entries_are_complete(self) -> None:
        for name, meta in TOOL_METADATA.items():
            assert meta.get("label"), f"{name} has no present-tense label"
            assert meta.get("label_past"), f"{name} has no past-tense label"
            assert meta.get("icon"), f"{name} has no icon"

    def test_every_icon_key_is_mapped_in_the_frontend(self) -> None:
        """An unmapped icon key silently degrades to the generic brain icon."""
        source = Path("web/src/components/ThinkingIndicator.ts").read_text()
        block = source.split("const ICON_MAP: Record<string, string> = {")[1].split("};")[0]
        mapped = set(re.findall(r"^\s*'?([a-z-]+)'?:", block, re.M))
        used = {meta["icon"] for meta in TOOL_METADATA.values()}
        assert not (used - mapped), f"icons missing from ICON_MAP: {sorted(used - mapped)}"


class TestGarminDetail:
    def test_snapshot_shows_the_date(self) -> None:
        detail = extract_tool_detail(
            "garmin_connect", {"action": "get_readiness_snapshot", "date_str": "2026-09-06"}
        )
        assert detail == "readiness snapshot · 2026-09-06"

    def test_activity_details_shows_the_id(self) -> None:
        detail = extract_tool_detail(
            "garmin_connect", {"action": "get_activity_details", "activity_id": "42"}
        )
        assert detail == "activity · 42"

    def test_activity_list_shows_filters(self) -> None:
        detail = extract_tool_detail(
            "garmin_connect",
            {"action": "get_activities", "activity_type": "cycling", "limit": 5},
        )
        assert detail == "recent activities · cycling · last 5"

    def test_unknown_action_degrades_readably(self) -> None:
        """A new action must not print as a bare snake_case identifier."""
        assert extract_tool_detail("garmin_connect", {"action": "get_new_metric"}) == "new metric"


class TestOtherToolDetails:
    def test_kv_store_shows_the_key(self) -> None:
        detail = extract_tool_detail("kv_store", {"action": "merge", "key": "cycling:progress"})
        assert detail == "merge: cycling:progress"

    def test_kv_list_shows_the_prefix(self) -> None:
        assert extract_tool_detail("kv_store", {"action": "list", "key": "cycling:"}) == (
            "list keys: cycling:*"
        )

    def test_garmin_workout_counts_edits(self) -> None:
        detail = extract_tool_detail(
            "garmin_workout", {"action": "update", "workout_id": "9", "edits": [1, 2]}
        )
        assert detail == "update workout 9 (2 edits)"

    def test_route_reads_as_a_journey(self) -> None:
        detail = extract_tool_detail(
            "get_route", {"origin": "Prague", "destination": "Brno", "mode": "bike"}
        )
        assert detail == "Prague → Brno (bike)"

    def test_place_search_includes_the_area(self) -> None:
        detail = extract_tool_detail("search_places", {"query": "coffee", "near": "Karlin"})
        assert detail == "coffee near Karlin"

    def test_place_search_omits_the_default_area(self) -> None:
        assert extract_tool_detail("search_places", {"query": "coffee", "near": "current"}) == (
            "coffee"
        )

    def test_title_change_shows_the_new_title(self) -> None:
        detail = extract_tool_detail("set_conversation_title", {"title": "🚴 Sunday ride"})
        assert detail == "🚴 Sunday ride"

    def test_whatsapp_shows_the_message(self) -> None:
        detail = extract_tool_detail("whatsapp", {"message": "Dinner at 7?"})
        assert detail == "Dinner at 7?"

    def test_unknown_tool_yields_no_detail(self) -> None:
        assert extract_tool_detail("not_a_tool", {"anything": 1}) is None

    def test_missing_args_never_raise(self) -> None:
        """tool_call args can arrive partial; extraction must degrade, not crash."""
        for name in TOOL_METADATA:
            extract_tool_detail(name, {})
            extract_tool_detail(name, {"action": ""})


class TestExtractToolDetail:
    """Tests for _extract_tool_detail function."""

    def test_web_search_extracts_query(self) -> None:
        """Should extract query from web_search tool args."""
        result = _extract_tool_detail("web_search", {"query": "best pizza in Prague"})
        assert result == "best pizza in Prague"

    def test_fetch_url_extracts_url(self) -> None:
        """Should extract URL from fetch_url tool args."""
        result = _extract_tool_detail("fetch_url", {"url": "https://example.com/page"})
        assert result == "https://example.com/page"

    def test_generate_image_extracts_prompt(self) -> None:
        """Should extract prompt from generate_image tool args."""
        result = _extract_tool_detail("generate_image", {"prompt": "A cat on a rainbow"})
        assert result == "A cat on a rainbow"

    def test_execute_code_extracts_first_line(self) -> None:
        """Should extract first line of code from execute_code tool args."""
        code = "print('Hello')\nprint('World')"
        result = _extract_tool_detail("execute_code", {"code": code})
        assert result == "print('Hello')"

    def test_execute_code_truncates_long_lines(self) -> None:
        """Should truncate long first lines to 50 chars."""
        code = "x = " + "a" * 100 + "\nmore code"
        result = _extract_tool_detail("execute_code", {"code": code})
        assert result is not None
        assert len(result) == 50

    def test_todoist_list_tasks(self) -> None:
        """Should extract action and filter for list_tasks."""
        result = _extract_tool_detail("todoist", {"action": "list_tasks", "filter": "today"})
        assert result == "list_tasks: today"

    def test_todoist_list_tasks_default_filter(self) -> None:
        """Should use 'all' as default filter for list_tasks."""
        result = _extract_tool_detail("todoist", {"action": "list_tasks"})
        assert result == "list_tasks: all"

    def test_todoist_add_task(self) -> None:
        """Should extract action and content for add_task."""
        result = _extract_tool_detail("todoist", {"action": "add_task", "content": "Buy milk"})
        assert result == "add_task: Buy milk"

    def test_todoist_add_task_truncates(self) -> None:
        """Should truncate long task content."""
        long_content = "x" * 100
        result = _extract_tool_detail("todoist", {"action": "add_task", "content": long_content})
        assert result == f"add_task: {'x' * 60}"

    def test_todoist_complete_task(self) -> None:
        """Should extract action and task_id for complete_task."""
        result = _extract_tool_detail("todoist", {"action": "complete_task", "task_id": "123456"})
        assert result == "complete_task: 123456"

    def test_todoist_list_projects(self) -> None:
        """Should return just action for list_projects."""
        result = _extract_tool_detail("todoist", {"action": "list_projects"})
        assert result == "list_projects"

    def test_unknown_tool_returns_none(self) -> None:
        """Should return None for unknown tool."""
        result = _extract_tool_detail("unknown_tool", {"data": "value"})
        assert result is None

    def test_missing_required_arg_returns_none(self) -> None:
        """Should return None when required arg is missing."""
        result = _extract_tool_detail("web_search", {})
        assert result is None


class TestFormatTodoistDetail:
    """Tests for _format_todoist_detail function."""

    def test_list_tasks_with_filter(self) -> None:
        """Should format list_tasks with filter."""
        result = _format_todoist_detail({"action": "list_tasks", "filter": "overdue"})
        assert result == "list_tasks: overdue"

    def test_list_tasks_without_filter(self) -> None:
        """Should use 'all' default for list_tasks."""
        result = _format_todoist_detail({"action": "list_tasks"})
        assert result == "list_tasks: all"

    def test_add_task(self) -> None:
        """Should format add_task with content."""
        result = _format_todoist_detail({"action": "add_task", "content": "Buy groceries"})
        assert result == "add_task: Buy groceries"

    def test_update_task(self) -> None:
        """Should format update_task with task_id."""
        result = _format_todoist_detail({"action": "update_task", "task_id": "abc123"})
        assert result == "update_task: abc123"

    def test_delete_task(self) -> None:
        """Should format delete_task with task_id."""
        result = _format_todoist_detail({"action": "delete_task", "task_id": "xyz789"})
        assert result == "delete_task: xyz789"

    def test_add_project(self) -> None:
        result = _format_todoist_detail({"action": "add_project", "project_name": "Work"})
        assert result == "add_project: Work"

    def test_share_project(self) -> None:
        result = _format_todoist_detail(
            {"action": "share_project", "collaborator_email": "teammate@example.com"}
        )
        assert result == "share_project: teammate@example.com"

    def test_add_section(self) -> None:
        result = _format_todoist_detail({"action": "add_section", "section_name": "Backlog"})
        assert result == "add_section: Backlog"

    def test_unknown_action(self) -> None:
        """Should return just action for unknown actions."""
        result = _format_todoist_detail({"action": "some_new_action"})
        assert result == "some_new_action"


class TestFormatCalendarDetail:
    """Tests for _format_calendar_detail function."""

    def test_list_events_with_range(self) -> None:
        result = _format_calendar_detail(
            {
                "action": "list_events",
                "calendar_id": "work",
                "time_min": "2024-01-01T00:00:00Z",
                "time_max": "2024-01-07T00:00:00Z",
            }
        )
        assert result == "list_events: work 2024-01-01T00:00:00Z → 2024-01-07T00:00:00Z"

    def test_create_event(self) -> None:
        result = _format_calendar_detail({"action": "create_event", "summary": "Sprint review"})
        assert result == "create_event: Sprint review"

    def test_delete_event(self) -> None:
        result = _format_calendar_detail({"action": "delete_event", "event_id": "evt-1"})
        assert result == "delete_event: evt-1"

    def test_respond_event(self) -> None:
        result = _format_calendar_detail({"action": "respond_event", "response_status": "accepted"})
        assert result == "respond_event: accepted"


class TestMemoryDiffDetail:
    """manage_memory pills show which entry changed and how (a compact diff).

    The detail is extracted at tool_start (pre-execution), so the DB still
    holds the OLD content - fetched via _fetch_memory_content, which tests
    patch to avoid real DB/context.
    """

    def test_add_shows_new_content_snippet(self) -> None:
        # add has no prior content, so no lookup is needed
        result = _extract_tool_detail(
            "manage_memory", {"operations": [{"action": "add", "content": "Runs marathons"}]}
        )
        assert result == "remembered: Runs marathons"

    def test_update_shows_old_to_new_diff(self) -> None:
        with patch(
            "src.agent.tool_display._fetch_memory_content", return_value="Drinks oat milk lattes"
        ):
            result = _extract_tool_detail(
                "manage_memory",
                {
                    "operations": [
                        {"action": "update", "id": "m1", "content": "Switched to black coffee"}
                    ]
                },
            )
        assert result == "updated: Drinks oat milk lattes → Switched to black coffee"

    def test_update_without_old_falls_back_to_new(self) -> None:
        with patch("src.agent.tool_display._fetch_memory_content", return_value=None):
            result = _extract_tool_detail(
                "manage_memory",
                {"operations": [{"action": "update", "id": "gone", "content": "New value"}]},
            )
        assert result == "updated: New value"

    def test_delete_shows_what_was_forgotten(self) -> None:
        with patch(
            "src.agent.tool_display._fetch_memory_content", return_value="Used to work at Acme"
        ):
            result = _extract_tool_detail(
                "manage_memory", {"operations": [{"action": "delete", "id": "m9"}]}
            )
        assert result == "forgot: Used to work at Acme"

    def test_delete_without_old_content_shows_bare_verb(self) -> None:
        with patch("src.agent.tool_display._fetch_memory_content", return_value=None):
            result = _extract_tool_detail(
                "manage_memory", {"operations": [{"action": "delete", "id": "m9"}]}
            )
        assert result == "forgot"

    def test_caps_at_two_entries_with_more_suffix(self) -> None:
        ops = [
            {"action": "add", "content": "Alpha"},
            {"action": "add", "content": "Beta"},
            {"action": "add", "content": "Gamma"},
        ]
        result = _extract_tool_detail("manage_memory", {"operations": ops})
        assert result == "remembered: Alpha; remembered: Beta (+1 more)"

    def test_long_snippets_are_truncated(self) -> None:
        with patch("src.agent.tool_display._fetch_memory_content", return_value="O" * 60):
            result = _format_memory_detail(
                {"operations": [{"action": "update", "id": "m1", "content": "N" * 60}]}
            )
        # each side of the diff is truncated to 35 chars (34 + ellipsis)
        assert result == f"updated: {'O' * 34}… → {'N' * 34}…"

    def test_non_list_operations_returns_default(self) -> None:
        assert _format_memory_detail({"operations": "nope"}) == "updated memory"


class TestSearchAndReadDetails:
    """search_memory shows its query; read_conversation shows the title."""

    def test_search_memory_extracts_query(self) -> None:
        result = _extract_tool_detail("search_memory", {"query": "coffee preferences"})
        assert result == "coffee preferences"

    def test_read_conversation_shows_title(self) -> None:
        with patch(
            "src.agent.tool_display._fetch_conversation_title", return_value="Trip planning"
        ):
            result = _extract_tool_detail("read_conversation", {"conversation_id": "c1"})
        assert result == "Trip planning"

    def test_read_conversation_without_title_returns_none(self) -> None:
        with patch("src.agent.tool_display._fetch_conversation_title", return_value=None):
            result = _extract_tool_detail("read_conversation", {"conversation_id": "c1"})
        assert result is None
