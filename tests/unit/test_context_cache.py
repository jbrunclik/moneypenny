"""Unit tests for Gemini context caching."""

from __future__ import annotations

import threading
import time
from collections.abc import Generator
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_google_genai._function_utils import convert_to_genai_function_declarations

if TYPE_CHECKING:
    from src.db.models import Database

from src.agent.context_cache import (
    CacheEntry,
    CacheProfile,
    ContextCacheManager,
    cache_content_hash,
    get_cached_content_name,
    supports_explicit_cache,
)
from src.agent.tools.artifacts import update_artifact
from src.agent.tools.browser import browser


def _make_tool(
    name: str = "test_tool",
    description: str = "A test tool.",
    schema: dict | None = None,
) -> MagicMock:
    """Deterministic fake LangChain tool (name, description, args schema)."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.args_schema.model_json_schema.return_value = schema or {"properties": {}}
    return tool


@pytest.fixture(autouse=True)
def mock_shared_registry() -> Generator[MagicMock]:
    """Isolate tests from the real DB-backed shared cache registry."""
    with patch("src.agent.context_cache.db") as mock_db:
        mock_db.get_context_cache_entry.return_value = None
        yield mock_db


def _wait_for_build(
    manager: object, cache_key: str = "standard:gemini-3-flash-preview", timeout: float = 2.0
) -> None:
    """Wait for the background cache build (spawned by get_or_create) to finish.

    Cache creation is now non-blocking: the first get_or_create returns None and
    builds in a daemon thread. Tests wait for that build to publish before
    asserting on the warmed cache.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        with manager._lock:  # type: ignore[attr-defined]
            if cache_key not in manager._creating:  # type: ignore[attr-defined]
                return
        time.sleep(0.005)  # poll interval


# ============ CacheProfile Tests ============


class TestCacheProfile:
    """Tests for CacheProfile enum."""

    def test_standard_profile(self) -> None:
        assert CacheProfile.STANDARD.value == "standard"

    def test_anonymous_profile(self) -> None:
        assert CacheProfile.ANONYMOUS.value == "anonymous"

    def test_planning_profile(self) -> None:
        assert CacheProfile.PLANNING.value == "planning"

    def test_no_program_cache_profiles(self) -> None:
        """One profile for all standing chats (agent / sports / language) - their
        instructions ride in the dynamic part - and none per program."""
        assert {p.name for p in CacheProfile} == {"STANDARD", "ANONYMOUS", "PLANNING", "STANDING"}

    def test_standing_profile_has_the_standard_static_prompt(self) -> None:
        from src.agent.prompts import get_static_prompt_for_profile

        assert get_static_prompt_for_profile("standing") == get_static_prompt_for_profile(
            "standard"
        )

    def test_ordinary_and_standing_chats_keep_separate_caches(self) -> None:
        """Review I1: both shared one key with different tool sets (kv_store),
        so alternating chats evicted each other's cache - every switch ran
        uncached and recreated a Gemini cache."""
        import time
        from unittest.mock import patch

        from src.agent import context_cache as cc
        from src.agent.tools import get_tools_for_request

        manager = type(cc._manager)()
        ordinary, standing = get_tools_for_request(), get_tools_for_request(standing=True)
        created: list[str] = []

        def fake_create(self: object, *args: object, **kwargs: object) -> str:
            created.append(f"cache-{len(created) + 1}")
            return created[-1]

        with (
            patch.object(type(manager), "_create_cache", fake_create),
            patch.object(type(manager), "_load_shared_entry", lambda *a, **k: None),
            patch.object(type(manager), "_store_shared_entry", lambda *a, **k: None),
        ):
            results = []
            for profile, tools in [
                (CacheProfile.STANDARD, ordinary),
                (CacheProfile.STANDING, standing),
                (CacheProfile.STANDARD, ordinary),
                (CacheProfile.STANDING, standing),
            ]:
                results.append(manager.get_or_create(profile, "gemini-x", tools))
                time.sleep(0.3)  # the create runs in the background

        assert results[2:] == ["cache-1", "cache-2"]
        assert len(created) == 2


# ============ get_static_prompt_for_profile Tests ============


class TestGetStaticPromptForProfile:
    """Tests for static prompt generation per profile."""

    def test_standard_includes_productivity(self) -> None:
        from src.agent.prompts import get_static_prompt_for_profile

        prompt = get_static_prompt_for_profile("standard")
        assert "Strategic Productivity Partner" in prompt
        assert "Core Principles" in prompt
        assert "Tools Available" in prompt

    def test_anonymous_excludes_productivity(self) -> None:
        from src.agent.prompts import get_static_prompt_for_profile

        prompt = get_static_prompt_for_profile("anonymous")
        assert "Strategic Productivity Partner" not in prompt
        assert "Tools Available" in prompt
        assert "Core Principles" in prompt

    def test_planning_includes_planner(self) -> None:
        from src.agent.prompts import get_static_prompt_for_profile

        prompt = get_static_prompt_for_profile("planning")
        assert "Strategic Productivity Partner" in prompt
        assert "Planner Mode" in prompt
        assert "Daily Planning Session" in prompt

    def test_standard_excludes_planner(self) -> None:
        from src.agent.prompts import get_static_prompt_for_profile

        prompt = get_static_prompt_for_profile("standard")
        assert "Planner Mode" not in prompt


# ============ get_dynamic_prompt_parts Tests ============


class TestGetDynamicPromptParts:
    """Tests for dynamic prompt generation."""

    def test_includes_datetime(self) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        result = get_dynamic_prompt_parts()
        assert "Current date and time:" in result

    def test_includes_user_name(self) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        result = get_dynamic_prompt_parts(user_name="Alice")
        assert "Alice" in result

    def test_includes_custom_instructions(self) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        result = get_dynamic_prompt_parts(custom_instructions="Always respond in Czech")
        assert "Always respond in Czech" in result

    @patch("src.agent.prompt_memory.db")
    def test_includes_memory_list(self, mock_db: MagicMock) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        mock_db.list_memories.return_value = []
        result = get_dynamic_prompt_parts(user_id="user-1")
        assert "Current Memories" in result

    @patch("src.agent.prompt_memory.db")
    def test_excludes_static_memory_instructions(self, mock_db: MagicMock) -> None:
        """The instructions are invariant, so they belong in the cached prefix.

        Bundling them with the per-request memory list re-sent ~1k uncached
        tokens on every single request.
        """
        from src.agent.prompts import get_dynamic_prompt_parts, get_static_prompt_for_profile

        mock_db.list_memories.return_value = []
        dynamic = get_dynamic_prompt_parts(user_id="user-1")

        assert "User Memory System" not in dynamic
        assert "User Memory System" in get_static_prompt_for_profile("standard")

    def test_excludes_memories_in_anonymous(self) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        result = get_dynamic_prompt_parts(user_id="user-1", anonymous_mode=True)
        assert "Current Memories" not in result

    def test_anonymous_static_prompt_has_no_memory_instructions(self) -> None:
        """Anonymous conversations have no memory tool, so no instructions either."""
        from src.agent.prompts import get_static_prompt_for_profile

        assert "User Memory System" not in get_static_prompt_for_profile("anonymous")

    def test_includes_force_tools(self) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        result = get_dynamic_prompt_parts(force_tools=["web_search"])
        assert "Mandatory Tool Usage" in result
        assert "web_search" in result

    def test_includes_the_standing_chat_section(self) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts
        from src.agent.standing import StandingContext

        result = get_dynamic_prompt_parts(
            standing=StandingContext(
                "sports", "Marathon Prep", "Coach the marathon plan", '{"goal": "sub-4h"}', "sports"
            )
        )
        assert "# This Chat: Marathon Prep" in result
        assert "Coach the marathon plan" in result
        assert "sub-4h" in result

    def test_language_instructions_reach_the_prompt(self) -> None:
        """A language chat's quiz rules ride in the per-turn part (the quiz XOR
        conversation contract the client's quiz renderer depends on)."""
        from src.agent.prompt_programs import format_program_kv_data
        from src.agent.prompt_texts.language import LANGUAGE_TUTOR_SYSTEM_PROMPT
        from src.agent.prompts import get_dynamic_prompt_parts
        from src.agent.standing import StandingContext

        instructions = LANGUAGE_TUTOR_SYSTEM_PROMPT.format(
            program_name="Spanish", program_id="spanish", kv_data_section=""
        )
        data = format_program_kv_data("language", {"kv_data": {}})
        result = get_dynamic_prompt_parts(
            standing=StandingContext("language", "Spanish", instructions, data, "language")
        )
        assert "```quiz" in result
        assert "No data stored yet" in result

    def test_standing_section_in_the_uncached_prompt(self) -> None:
        from src.agent.prompts import get_system_prompt
        from src.agent.standing import StandingContext

        prompt = get_system_prompt(
            standing=StandingContext("agent", "VWCE Watcher", "Watch VWCE weekly", None, "agent:a1")
        )
        assert "# This Chat: VWCE Watcher" in prompt
        assert "Watch VWCE weekly" in prompt


# ============ Cache invalidation by content ============


def _builds(*contents: tuple[str, list[Any]]) -> int:
    """How many caches get_or_create builds for these (prompt, tools) in turn."""
    manager = ContextCacheManager()
    with (
        patch("src.agent.context_cache.Config") as config,
        patch.object(manager, "_create_cache", return_value="cachedContents/c") as create,
        patch("src.agent.context_cache.get_static_prompt_for_profile") as prompt_for,
    ):
        config.GEMINI_API_KEY = "test-key"
        config.CONTEXT_CACHE_TTL_SECONDS = 3600
        config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300
        config.CONTEXT_CACHE_EXTEND_AHEAD_SECONDS = 600
        for prompt, tools in contents:
            prompt_for.return_value = prompt
            manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", tools)
            _wait_for_build(manager)
        return create.call_count


class TestCacheInvalidation:
    """The cache is rebuilt exactly when what it holds - the static prompt and
    the tool declarations - changes."""

    def test_same_content_reuses_the_cache(self) -> None:
        tools = [_make_tool("tool_a"), _make_tool("tool_b")]
        assert _builds(("prompt", tools), ("prompt", tools)) == 1

    def test_tool_order_is_irrelevant(self) -> None:
        a, b = _make_tool("tool_a"), _make_tool("tool_b")
        assert _builds(("prompt", [b, a]), ("prompt", [a, b])) == 1

    def test_a_prompt_change_rebuilds(self) -> None:
        tools = [_make_tool("tool_a")]
        assert _builds(("prompt v1", tools), ("prompt v2", tools)) == 2

    def test_a_tool_change_rebuilds(self) -> None:
        assert _builds(("prompt", [_make_tool("tool_a")]), ("prompt", [_make_tool("tool_b")])) == 2

    def test_a_description_change_rebuilds(self) -> None:
        """A docstring change must invalidate the cache - the cached function
        declarations would otherwise keep the stale description until TTL."""
        old = [_make_tool("tool_a", description="old")]
        new = [_make_tool("tool_a", description="new")]
        assert _builds(("prompt", old), ("prompt", new)) == 2

    def test_a_schema_change_rebuilds(self) -> None:
        """A new tool parameter must invalidate the cache."""
        old = [_make_tool("tool_a", schema={"properties": {"query": {}}})]
        new = [_make_tool("tool_a", schema={"properties": {"query": {}, "queries": {}}})]
        assert _builds(("prompt", old), ("prompt", new)) == 2

    def test_an_unreadable_schema_still_caches(self) -> None:
        """Schema extraction failure degrades to a weaker key, not a crash."""
        broken = _make_tool("tool_a")
        broken.args_schema.model_json_schema.side_effect = TypeError("no schema")
        assert _builds(("prompt", [broken])) == 1


# ============ ContextCacheManager Tests ============


class TestContextCacheManager:
    """Tests for ContextCacheManager."""

    def _make_mock_tool(self, name: str = "test_tool") -> MagicMock:
        return _make_tool(name)

    @patch("src.agent.context_cache.Config")
    def test_get_or_create_creates_cache(self, mock_config: MagicMock) -> None:
        """First call should create a new cache."""
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300
        mock_config.CONTEXT_CACHE_EXTEND_AHEAD_SECONDS = 600

        manager = ContextCacheManager()
        tool = self._make_mock_tool()

        with (
            patch.object(manager, "_create_cache", return_value="cachedContents/abc123"),
            patch(
                "src.agent.context_cache.get_static_prompt_for_profile",
                return_value="static prompt",
            ),
        ):
            # First call falls back to uncached (None) and builds in the background.
            result = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])
            assert result is None
            _wait_for_build(manager)
            # Once the build publishes, subsequent calls get the warm cache.
            result2 = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])

        assert result2 == "cachedContents/abc123"

    @patch("src.agent.context_cache.Config")
    def test_cache_hit_no_api_call(self, mock_config: MagicMock) -> None:
        """Second call with same params should return cached without API call."""
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300
        mock_config.CONTEXT_CACHE_EXTEND_AHEAD_SECONDS = 600

        manager = ContextCacheManager()
        tool = self._make_mock_tool()

        with (
            patch.object(
                manager, "_create_cache", return_value="cachedContents/abc123"
            ) as mock_create,
            patch(
                "src.agent.context_cache.get_static_prompt_for_profile",
                return_value="static prompt",
            ),
        ):
            # First call triggers a background build and falls back to uncached
            result1 = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])
            _wait_for_build(manager)
            # Second call hits the now-warm cache
            result2 = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])

        assert result1 is None
        assert result2 == "cachedContents/abc123"
        assert mock_create.call_count == 1  # Only built once

    @patch("src.agent.context_cache.Config")
    def test_content_hash_change_triggers_new_cache(self, mock_config: MagicMock) -> None:
        """Changed prompt content should trigger new cache creation."""
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300
        mock_config.CONTEXT_CACHE_EXTEND_AHEAD_SECONDS = 600

        manager = ContextCacheManager()
        tool = self._make_mock_tool()
        call_count = 0

        def create_side_effect(*args: object, **kwargs: object) -> str:
            nonlocal call_count
            call_count += 1
            return f"cachedContents/cache{call_count}"

        prompt_values = iter(["prompt v1", "prompt v2"])

        with (
            patch.object(manager, "_create_cache", side_effect=create_side_effect),
            patch(
                "src.agent.context_cache.get_static_prompt_for_profile",
                side_effect=lambda _: next(prompt_values),
            ),
        ):
            result1 = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])
            _wait_for_build(manager)
            # Second call sees a different content hash -> drift -> rebuild.
            result2 = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])
            _wait_for_build(manager)

        assert result1 is None and result2 is None
        assert call_count == 2  # two distinct background builds (v1, then v2)
        assert (
            manager._caches["standard:gemini-3-flash-preview"].cache_name == "cachedContents/cache2"
        )

    @patch("src.agent.context_cache.Config")
    def test_expired_cache_triggers_renewal(self, mock_config: MagicMock) -> None:
        """Cache near expiry should be renewed."""
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300
        mock_config.CONTEXT_CACHE_EXTEND_AHEAD_SECONDS = 600

        manager = ContextCacheManager()
        tool = self._make_mock_tool()

        # Pre-populate with an about-to-expire entry
        now = time.time()
        manager._caches["standard:gemini-3-flash-preview"] = CacheEntry(
            cache_name="cachedContents/old",
            content_hash=cache_content_hash("static prompt", [tool]),
            created_at=now - 3500,
            expires_at=now + 100,  # Expires in 100s, which is < 300s buffer
        )

        with (
            patch.object(manager, "_create_cache", return_value="cachedContents/renewed"),
            patch(
                "src.agent.context_cache.get_static_prompt_for_profile",
                return_value="static prompt",
            ),
        ):
            # About-to-expire entry isn't a hit -> triggers a background rebuild.
            result = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])
            assert result is None
            _wait_for_build(manager)
            result2 = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])

        assert result2 == "cachedContents/renewed"

    def _seed_entry(
        self, manager: ContextCacheManager, tool: MagicMock, expires_in: float
    ) -> CacheEntry:
        now = time.time()
        entry = CacheEntry(
            cache_name="cachedContents/live",
            content_hash=cache_content_hash("static prompt", [tool]),
            created_at=now - 3000,
            expires_at=now + expires_in,
        )
        manager._caches["standard:gemini-3-flash-preview"] = entry
        return entry

    @staticmethod
    def _wait_for_extension(manager: ContextCacheManager, timeout: float = 2.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with manager._lock:
                if not manager._extending:
                    return
            time.sleep(0.01)  # poll interval
        raise AssertionError("background cache extension did not finish")

    @patch("src.agent.context_cache.Config")
    def test_hit_near_expiry_extends_ttl_in_background(self, mock_config: MagicMock) -> None:
        """A cache still in use shortly before its renewal buffer gets its TTL
        extended (sliding expiry) instead of lapsing into a miss + rebuild -
        in Sep 2026 36% of rebuilds happened mid-session this way."""
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300
        mock_config.CONTEXT_CACHE_EXTEND_AHEAD_SECONDS = 600
        manager = ContextCacheManager()
        tool = self._make_mock_tool()
        self._seed_entry(manager, tool, expires_in=700)  # inside 300+600 window

        with (
            patch.object(manager, "_extend_cache", return_value=True) as mock_extend,
            patch.object(manager, "_store_shared_entry") as mock_store,
            patch(
                "src.agent.context_cache.get_static_prompt_for_profile",
                return_value="static prompt",
            ),
        ):
            result = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])
            self._wait_for_extension(manager)

        assert result == "cachedContents/live"  # still served - no miss
        mock_extend.assert_called_once_with("cachedContents/live", 3600)
        entry = manager._caches["standard:gemini-3-flash-preview"]
        assert entry.expires_at > time.time() + 3500
        mock_store.assert_called_once()

    @patch("src.agent.context_cache.Config")
    def test_no_extension_far_from_expiry(self, mock_config: MagicMock) -> None:
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300
        mock_config.CONTEXT_CACHE_EXTEND_AHEAD_SECONDS = 600
        manager = ContextCacheManager()
        tool = self._make_mock_tool()
        self._seed_entry(manager, tool, expires_in=3000)

        with (
            patch.object(manager, "_extend_cache") as mock_extend,
            patch(
                "src.agent.context_cache.get_static_prompt_for_profile",
                return_value="static prompt",
            ),
        ):
            manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])

        mock_extend.assert_not_called()

    @patch("src.agent.context_cache.Config")
    def test_failed_extension_keeps_entry(self, mock_config: MagicMock) -> None:
        """A failed update leaves the entry alone; normal renewal takes over later."""
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300
        mock_config.CONTEXT_CACHE_EXTEND_AHEAD_SECONDS = 600
        manager = ContextCacheManager()
        tool = self._make_mock_tool()
        seeded = self._seed_entry(manager, tool, expires_in=700)

        with (
            patch.object(manager, "_extend_cache", return_value=False),
            patch(
                "src.agent.context_cache.get_static_prompt_for_profile",
                return_value="static prompt",
            ),
        ):
            result = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])
            self._wait_for_extension(manager)

        assert result == "cachedContents/live"
        assert manager._caches["standard:gemini-3-flash-preview"] == seeded

    @patch("src.agent.context_cache.Config")
    def test_creation_failure_returns_none(self, mock_config: MagicMock) -> None:
        """Cache creation failure should return None (graceful fallback)."""
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300
        mock_config.CONTEXT_CACHE_EXTEND_AHEAD_SECONDS = 600

        manager = ContextCacheManager()
        tool = self._make_mock_tool()

        with (
            patch.object(manager, "_create_cache", return_value=None),
            patch(
                "src.agent.context_cache.get_static_prompt_for_profile",
                return_value="static prompt",
            ),
        ):
            result = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])

        assert result is None

    @patch("src.agent.context_cache.Config")
    def test_exception_returns_none(self, mock_config: MagicMock) -> None:
        """Any exception should return None (graceful fallback)."""
        mock_config.GEMINI_API_KEY = "test-key"

        manager = ContextCacheManager()
        tool = self._make_mock_tool()

        with patch(
            "src.agent.context_cache.get_static_prompt_for_profile",
            side_effect=RuntimeError("boom"),
        ):
            result = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])

        assert result is None

    @patch("src.agent.context_cache.Config")
    def test_thread_safety(self, mock_config: MagicMock) -> None:
        """Concurrent calls should not produce errors or duplicate cache creations."""
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300
        mock_config.CONTEXT_CACHE_EXTEND_AHEAD_SECONDS = 600

        manager = ContextCacheManager()
        tool = self._make_mock_tool()
        create_count = 0
        create_lock = threading.Lock()
        # The build finishes only after every worker returned: a sleep let a
        # late worker on a loaded run see the warm cache (flaky in make test)
        workers_done = threading.Event()

        def slow_create(*args: object, **kwargs: object) -> str:
            nonlocal create_count
            workers_done.wait(timeout=5)
            with create_lock:
                create_count += 1
            return "cachedContents/thread-safe"

        results: list[str | None] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                r = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])
                results.append(r)
            except Exception as e:  # noqa: BLE001 - collected and asserted after join
                errors.append(e)

        with (
            patch.object(manager, "_create_cache", side_effect=slow_create),
            patch(
                "src.agent.context_cache.get_static_prompt_for_profile",
                return_value="static prompt",
            ),
        ):
            threads = [threading.Thread(target=worker) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            workers_done.set()

            # Cold miss: every concurrent caller serves uncached (None) while a
            # single background build runs - no thundering herd of create()s.
            assert not errors
            assert all(r is None for r in results)
            _wait_for_build(manager)
            assert create_count == 1

            # Subsequent call picks up the warm cache the build published.
            warm = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])

        assert warm == "cachedContents/thread-safe"


# ============ Cross-Worker Shared Registry Tests ============


class TestSharedCacheRegistry:
    """The DB-backed registry shares one Gemini cache across gunicorn workers."""

    def _make_mock_tool(self, name: str = "test_tool") -> MagicMock:
        return _make_tool(name)

    @patch("src.agent.context_cache.Config")
    def test_adopts_cache_created_by_another_worker(
        self, mock_config: MagicMock, mock_shared_registry: MagicMock
    ) -> None:
        """A valid DB entry from another worker is reused without creating."""
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300
        mock_config.CONTEXT_CACHE_EXTEND_AHEAD_SECONDS = 600

        content_hash = cache_content_hash("static prompt", [_make_tool()])
        mock_shared_registry.get_context_cache_entry.return_value = {
            "cache_name": "cachedContents/other-worker",
            "content_hash": content_hash,
            "created_at": time.time(),
            "expires_at": time.time() + 3600,
        }

        manager = ContextCacheManager()
        with (
            patch.object(manager, "_create_cache") as mock_create,
            patch(
                "src.agent.context_cache.get_static_prompt_for_profile",
                return_value="static prompt",
            ),
        ):
            result = manager.get_or_create(
                CacheProfile.STANDARD, "gemini-3-flash-preview", [self._make_mock_tool()]
            )

        assert result == "cachedContents/other-worker"
        mock_create.assert_not_called()

    @patch("src.agent.context_cache.Config")
    def test_stale_hash_in_registry_triggers_creation(
        self, mock_config: MagicMock, mock_shared_registry: MagicMock
    ) -> None:
        """A DB entry for an older prompt/tool set must not be adopted."""
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300
        mock_config.CONTEXT_CACHE_EXTEND_AHEAD_SECONDS = 600

        mock_shared_registry.get_context_cache_entry.return_value = {
            "cache_name": "cachedContents/stale",
            "content_hash": "different-hash",
            "created_at": time.time(),
            "expires_at": time.time() + 3600,
        }

        manager = ContextCacheManager()
        with (
            patch.object(manager, "_create_cache", return_value="cachedContents/fresh"),
            patch(
                "src.agent.context_cache.get_static_prompt_for_profile",
                return_value="static prompt",
            ),
        ):
            # Stale DB entry isn't adopted -> cold miss -> background build.
            result = manager.get_or_create(
                CacheProfile.STANDARD, "gemini-3-flash-preview", [self._make_mock_tool()]
            )
            assert result is None
            _wait_for_build(manager)
            warm = manager.get_or_create(
                CacheProfile.STANDARD, "gemini-3-flash-preview", [self._make_mock_tool()]
            )

        assert warm == "cachedContents/fresh"

    @patch("src.agent.context_cache.Config")
    def test_created_cache_is_published_to_registry(
        self, mock_config: MagicMock, mock_shared_registry: MagicMock
    ) -> None:
        """A newly created cache is stored in the DB for other workers."""
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300
        mock_config.CONTEXT_CACHE_EXTEND_AHEAD_SECONDS = 600

        manager = ContextCacheManager()
        with (
            patch.object(manager, "_create_cache", return_value="cachedContents/new"),
            patch(
                "src.agent.context_cache.get_static_prompt_for_profile",
                return_value="static prompt",
            ),
        ):
            result = manager.get_or_create(
                CacheProfile.STANDARD, "gemini-3-flash-preview", [self._make_mock_tool()]
            )
            assert result is None
            _wait_for_build(manager)

        mock_shared_registry.store_context_cache_entry.assert_called_once()
        args = mock_shared_registry.store_context_cache_entry.call_args.args
        assert args[0] == "standard:gemini-3-flash-preview"
        assert args[1] == "cachedContents/new"

    @patch("src.agent.context_cache.Config")
    def test_registry_failure_degrades_to_local_creation(
        self, mock_config: MagicMock, mock_shared_registry: MagicMock
    ) -> None:
        """DB errors must not break caching - the worker creates its own."""
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300
        mock_config.CONTEXT_CACHE_EXTEND_AHEAD_SECONDS = 600

        mock_shared_registry.get_context_cache_entry.side_effect = RuntimeError("db down")
        mock_shared_registry.store_context_cache_entry.side_effect = RuntimeError("db down")

        manager = ContextCacheManager()
        with (
            patch.object(manager, "_create_cache", return_value="cachedContents/local"),
            patch(
                "src.agent.context_cache.get_static_prompt_for_profile",
                return_value="static prompt",
            ),
        ):
            # DB lookup fails -> cold miss -> background build; the failing DB
            # store is swallowed and the in-process cache still warms.
            result = manager.get_or_create(
                CacheProfile.STANDARD, "gemini-3-flash-preview", [self._make_mock_tool()]
            )
            assert result is None
            _wait_for_build(manager)
            warm = manager.get_or_create(
                CacheProfile.STANDARD, "gemini-3-flash-preview", [self._make_mock_tool()]
            )

        assert warm == "cachedContents/local"


# ============ Context Cache DB Mixin Tests ============


class TestContextCacheDbMixin:
    """Tests for the context_cache table operations (real SQLite)."""

    def test_store_and_get(self, test_database: Database) -> None:
        now = time.time()
        test_database.store_context_cache_entry(
            "standard:gemini-x", "cachedContents/abc", "hash1", now, now + 3600
        )
        entry = test_database.get_context_cache_entry("standard:gemini-x")
        assert entry is not None
        assert entry["cache_name"] == "cachedContents/abc"
        assert entry["content_hash"] == "hash1"

    def test_get_missing_returns_none(self, test_database: Database) -> None:
        assert test_database.get_context_cache_entry("nope:gemini-x") is None

    def test_expired_entry_returns_none(self, test_database: Database) -> None:
        now = time.time()
        test_database.store_context_cache_entry(
            "standard:gemini-x", "cachedContents/old", "hash1", now - 7200, now - 3600
        )
        assert test_database.get_context_cache_entry("standard:gemini-x") is None

    def test_store_replaces_existing(self, test_database: Database) -> None:
        now = time.time()
        test_database.store_context_cache_entry(
            "standard:gemini-x", "cachedContents/v1", "hash1", now, now + 3600
        )
        test_database.store_context_cache_entry(
            "standard:gemini-x", "cachedContents/v2", "hash2", now, now + 3600
        )
        entry = test_database.get_context_cache_entry("standard:gemini-x")
        assert entry is not None
        assert entry["cache_name"] == "cachedContents/v2"
        assert entry["content_hash"] == "hash2"


# ============ _create_cache Tests ============


class TestCreateCache:
    """Tests for the actual cache creation / tool conversion."""

    def _make_mock_tool(self, name: str = "test_tool") -> MagicMock:
        return _make_tool(name)

    @patch("src.agent.context_cache.Config")
    def test_single_tool_return_normalized_to_list(self, mock_config: MagicMock) -> None:
        """Older langchain-google-genai returns a single Tool, not a list.

        Regression test: CreateCachedContentConfig.tools requires a list, so a
        single Tool must be wrapped before being passed through.
        """
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600

        manager = ContextCacheManager()
        single_tool = MagicMock(name="single_tool")
        mock_client = MagicMock()
        mock_client.caches.create.return_value.name = "cachedContents/xyz"

        with (
            patch.object(manager, "_get_client", return_value=mock_client),
            patch(
                "src.agent.context_cache.convert_to_genai_function_declarations",
                return_value=single_tool,
            ),
            patch("google.genai.types.CreateCachedContentConfig") as mock_config_cls,
        ):
            result = manager._create_cache(
                CacheProfile.STANDARD,
                "gemini-3-flash-preview",
                "static prompt",
                [self._make_mock_tool()],
            )

        assert result == "cachedContents/xyz"
        passed_tools = mock_config_cls.call_args.kwargs["tools"]
        assert passed_tools == [single_tool]

    @patch("src.agent.context_cache.Config")
    def test_list_tool_return_passed_through(self, mock_config: MagicMock) -> None:
        """Newer langchain-google-genai returns list[Tool]; it must pass through as-is."""
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600

        manager = ContextCacheManager()
        tool_list = [MagicMock(name="tool_a"), MagicMock(name="tool_b")]
        mock_client = MagicMock()
        mock_client.caches.create.return_value.name = "cachedContents/xyz"

        with (
            patch.object(manager, "_get_client", return_value=mock_client),
            patch(
                "src.agent.context_cache.convert_to_genai_function_declarations",
                return_value=tool_list,
            ),
            patch("google.genai.types.CreateCachedContentConfig") as mock_config_cls,
        ):
            result = manager._create_cache(
                CacheProfile.STANDARD,
                "gemini-3-flash-preview",
                "static prompt",
                [self._make_mock_tool()],
            )

        assert result == "cachedContents/xyz"
        passed_tools = mock_config_cls.call_args.kwargs["tools"]
        assert passed_tools == tool_list


# ============ get_cached_content_name Tests ============


class TestGetCachedContentName:
    """Tests for the convenience function."""

    @patch("src.agent.context_cache.Config")
    def test_returns_none_when_disabled(self, mock_config: MagicMock) -> None:
        """Should return None when CONTEXT_CACHE_ENABLED is false."""
        mock_config.CONTEXT_CACHE_ENABLED = False
        result = get_cached_content_name(CacheProfile.STANDARD, "gemini-3-flash-preview", [])
        assert result is None

    @patch("src.agent.context_cache._manager")
    @patch("src.agent.context_cache.Config")
    def test_delegates_to_manager(self, mock_config: MagicMock, mock_manager: MagicMock) -> None:
        """When enabled, should delegate to the manager singleton."""
        mock_config.CONTEXT_CACHE_ENABLED = True
        mock_manager.get_or_create.return_value = "cachedContents/test"

        result = get_cached_content_name(CacheProfile.STANDARD, "gemini-3-flash-preview", [])

        assert result == "cachedContents/test"
        mock_manager.get_or_create.assert_called_once_with(
            CacheProfile.STANDARD, "gemini-3-flash-preview", []
        )

    @patch("src.agent.context_cache._manager")
    @patch("src.agent.context_cache.Config")
    def test_implicit_only_models_skip_the_cache_api(
        self, mock_config: MagicMock, mock_manager: MagicMock
    ) -> None:
        """Gemini 4 rejects caches.create with a 400: never call it for them."""
        mock_config.CONTEXT_CACHE_ENABLED = True

        result = get_cached_content_name(CacheProfile.STANDARD, "gemini-4-hydrogen", [])

        assert result is None
        mock_manager.get_or_create.assert_not_called()


class TestSupportsExplicitCache:
    def test_gemini_3_supports_it(self) -> None:
        assert supports_explicit_cache("gemini-3.8-flash")

    def test_gemini_4_is_implicit_only(self) -> None:
        assert not supports_explicit_cache("gemini-4-hydrogen")
        assert not supports_explicit_cache("gemini-4-carbon")


# ============ CacheEntry Tests ============


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_fields(self) -> None:
        entry = CacheEntry(
            cache_name="cachedContents/test",
            content_hash="abc123",
            created_at=1000.0,
            expires_at=4600.0,
        )
        assert entry.cache_name == "cachedContents/test"
        assert entry.content_hash == "abc123"
        assert entry.created_at == 1000.0
        assert entry.expires_at == 4600.0


# ============ Nested tool schemas ============


class TestNestedToolSchemas:
    """Pydantic puts nested argument models under `$defs` and langchain logs
    "Key '$defs' is not supported in schema, ignoring" for them. That is only
    noise while langchain inlines each `$ref` before dropping `$defs`; these
    tests catch an upgrade that stops inlining and sends Gemini a bare array."""

    @staticmethod
    def _items(tool: Any, field: str) -> dict[str, Any]:
        converted = convert_to_genai_function_declarations([tool])
        genai_tool = converted[0] if isinstance(converted, list) else converted
        declaration = genai_tool.model_dump(exclude_none=True)["function_declarations"][0]
        items: dict[str, Any] = declaration["parameters"]["properties"][field]["items"]
        return items

    def test_artifact_edits_reach_gemini(self) -> None:
        items = self._items(update_artifact, "edits")
        assert set(items["properties"]) == {"find", "replace"}
        assert items["required"] == ["find", "replace"]

    def test_browser_steps_reach_gemini(self) -> None:
        items = self._items(browser, "actions")
        assert {"action", "url", "selector", "text"} <= set(items["properties"])
        assert items["required"] == ["action"]
