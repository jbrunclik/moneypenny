"""Tests for tool display metadata and detail extraction.

Every tool the model can call must have a TOOL_METADATA entry: without one the
thinking trace falls back to a raw "Used <function_name>" pill. A Sep 2026
audit found three of the five most-called tools (garmin_connect, kv_store,
cite_sources) in exactly that state.
"""

import re
from pathlib import Path

from src.agent.tool_display import (
    _CONDITIONAL_TOOLS,
    TOOL_METADATA,
    extract_tool_detail,
)
from src.agent.tools import get_available_tools


class TestMetadataCoverage:
    def test_every_bindable_tool_has_display_metadata(self) -> None:
        bindable = {tool.name for tool in get_available_tools()} | set(_CONDITIONAL_TOOLS)
        missing = sorted(bindable - set(TOOL_METADATA))
        assert not missing, f"tools would render as raw function names: {missing}"

    def test_no_metadata_for_tools_that_do_not_exist(self) -> None:
        bindable = {tool.name for tool in get_available_tools()} | set(_CONDITIONAL_TOOLS)
        # google_calendar is registered only when credentials are configured.
        unknown = sorted(set(TOOL_METADATA) - bindable - {"google_calendar"})
        assert not unknown

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

    def test_cite_sources_counts_sources(self) -> None:
        detail = extract_tool_detail("cite_sources", {"sources": [{"url": "a"}, {"url": "b"}]})
        assert detail == "2 sources"

    def test_cite_sources_singular(self) -> None:
        assert extract_tool_detail("cite_sources", {"sources": [{"url": "a"}]}) == "1 source"

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
