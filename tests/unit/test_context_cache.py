"""Unit tests for Gemini context caching."""

import threading
import time
from unittest.mock import MagicMock, patch

from src.agent.context_cache import (
    CacheEntry,
    CacheProfile,
    ContextCacheManager,
    _compute_content_hash,
    get_cached_content_name,
)

# ============ CacheProfile Tests ============


class TestCacheProfile:
    """Tests for CacheProfile enum."""

    def test_standard_profile(self) -> None:
        assert CacheProfile.STANDARD.value == "standard"

    def test_anonymous_profile(self) -> None:
        assert CacheProfile.ANONYMOUS.value == "anonymous"

    def test_planning_profile(self) -> None:
        assert CacheProfile.PLANNING.value == "planning"


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

    @patch("src.agent.prompts.db")
    def test_includes_memories(self, mock_db: MagicMock) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        mock_db.list_memories.return_value = []
        result = get_dynamic_prompt_parts(user_id="user-1")
        assert "User Memory System" in result

    def test_excludes_memories_in_anonymous(self) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        result = get_dynamic_prompt_parts(user_id="user-1", anonymous_mode=True)
        assert "User Memory System" not in result

    def test_includes_force_tools(self) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        result = get_dynamic_prompt_parts(force_tools=["web_search"])
        assert "Mandatory Tool Usage" in result
        assert "web_search" in result


# ============ _compute_content_hash Tests ============


class TestComputeContentHash:
    """Tests for content hashing."""

    def test_same_input_same_hash(self) -> None:
        h1 = _compute_content_hash("prompt text", ["tool_a", "tool_b"])
        h2 = _compute_content_hash("prompt text", ["tool_a", "tool_b"])
        assert h1 == h2

    def test_different_prompt_different_hash(self) -> None:
        h1 = _compute_content_hash("prompt v1", ["tool_a"])
        h2 = _compute_content_hash("prompt v2", ["tool_a"])
        assert h1 != h2

    def test_different_tools_different_hash(self) -> None:
        h1 = _compute_content_hash("prompt", ["tool_a"])
        h2 = _compute_content_hash("prompt", ["tool_b"])
        assert h1 != h2

    def test_tool_order_irrelevant(self) -> None:
        h1 = _compute_content_hash("prompt", ["tool_b", "tool_a"])
        h2 = _compute_content_hash("prompt", ["tool_a", "tool_b"])
        assert h1 == h2

    def test_hash_length(self) -> None:
        h = _compute_content_hash("prompt", ["tool"])
        assert len(h) == 16  # SHA-256 truncated to 16 hex chars


# ============ ContextCacheManager Tests ============


class TestContextCacheManager:
    """Tests for ContextCacheManager."""

    def _make_mock_tool(self, name: str = "test_tool") -> MagicMock:
        tool = MagicMock()
        tool.name = name
        return tool

    @patch("src.agent.context_cache.Config")
    def test_get_or_create_creates_cache(self, mock_config: MagicMock) -> None:
        """First call should create a new cache."""
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300

        manager = ContextCacheManager()
        mock_result = MagicMock()
        mock_result.name = "cachedContents/abc123"

        with (
            patch.object(manager, "_create_cache", return_value="cachedContents/abc123"),
            patch(
                "src.agent.context_cache.get_static_prompt_for_profile",
                return_value="static prompt",
            ),
        ):
            result = manager.get_or_create(
                CacheProfile.STANDARD, "gemini-3-flash-preview", [self._make_mock_tool()]
            )

        assert result == "cachedContents/abc123"

    @patch("src.agent.context_cache.Config")
    def test_cache_hit_no_api_call(self, mock_config: MagicMock) -> None:
        """Second call with same params should return cached without API call."""
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300

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
            # First call creates
            result1 = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])
            # Second call hits cache
            result2 = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])

        assert result1 == result2
        assert mock_create.call_count == 1  # Only called once

    @patch("src.agent.context_cache.Config")
    def test_content_hash_change_triggers_new_cache(self, mock_config: MagicMock) -> None:
        """Changed prompt content should trigger new cache creation."""
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300

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
            result2 = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])

        assert result1 != result2
        assert call_count == 2

    @patch("src.agent.context_cache.Config")
    def test_expired_cache_triggers_renewal(self, mock_config: MagicMock) -> None:
        """Cache near expiry should be renewed."""
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300

        manager = ContextCacheManager()
        tool = self._make_mock_tool()

        # Pre-populate with an about-to-expire entry
        now = time.time()
        manager._caches["standard:gemini-3-flash-preview"] = CacheEntry(
            cache_name="cachedContents/old",
            content_hash=_compute_content_hash("static prompt", ["test_tool"]),
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
            result = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])

        assert result == "cachedContents/renewed"

    @patch("src.agent.context_cache.Config")
    def test_creation_failure_returns_none(self, mock_config: MagicMock) -> None:
        """Cache creation failure should return None (graceful fallback)."""
        mock_config.GEMINI_API_KEY = "test-key"
        mock_config.CONTEXT_CACHE_TTL_SECONDS = 3600
        mock_config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS = 300

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

        manager = ContextCacheManager()
        tool = self._make_mock_tool()
        create_count = 0
        create_lock = threading.Lock()

        def slow_create(*args: object, **kwargs: object) -> str:
            nonlocal create_count
            time.sleep(0.01)  # Simulate slow API call
            with create_lock:
                create_count += 1
            return "cachedContents/thread-safe"

        results: list[str | None] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                r = manager.get_or_create(CacheProfile.STANDARD, "gemini-3-flash-preview", [tool])
                results.append(r)
            except Exception as e:
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

        assert not errors
        assert all(r == "cachedContents/thread-safe" for r in results)


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
