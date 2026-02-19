"""Gemini Context Caching for static system prompts.

Caches the large static system prompt + tool definitions using Gemini's
Context Caching API, reducing input token costs by ~75% on cached tokens.

Cache profiles:
- standard: BASE + TOOLS_BASE + PRODUCTIVITY + CONTEXT (authenticated users)
- anonymous: BASE + TOOLS_BASE + CONTEXT (anonymous mode)
- planning: BASE + TOOLS_BASE + PRODUCTIVITY + CONTEXT + PLANNER (planner view)

Dynamic content (date/time, user context, memories) is NOT cached and is
passed as a HumanMessage with [CONTEXT] markers.

Fallback: On any cache operation failure, returns None and the caller
falls back to the uncached path (SystemMessage + bind_tools).
"""

import hashlib
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.agent.prompts import get_static_prompt_for_profile
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


class CacheProfile(StrEnum):
    """Cache profile determines which static prompt sections are included."""

    STANDARD = "standard"
    ANONYMOUS = "anonymous"
    PLANNING = "planning"


@dataclass
class CacheEntry:
    """Tracks a single cached content entry."""

    cache_name: str
    content_hash: str
    created_at: float
    expires_at: float


def _compute_content_hash(prompt: str, tool_names: list[str]) -> str:
    """Compute SHA-256 hash for cache invalidation on prompt/tool changes."""
    content = prompt + "\n" + ",".join(sorted(tool_names))
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class ContextCacheManager:
    """Manages Gemini context caches for different profiles.

    Thread-safe singleton that lazily creates caches on first request.
    Content-addressed via hash: prompt/tool changes trigger new cache creation.
    Old caches expire naturally via TTL.
    """

    def __init__(self) -> None:
        self._caches: dict[str, CacheEntry] = {}
        self._client: Any | None = None
        self._lock = threading.Lock()

    def _get_client(self) -> Any:
        """Lazy-initialize the google.genai Client."""
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=Config.GEMINI_API_KEY)
        return self._client

    def get_or_create(
        self,
        profile: CacheProfile,
        model_name: str,
        tools: list[Any],
    ) -> str | None:
        """Get an existing cache or create a new one.

        Args:
            profile: Which static prompt profile to cache
            model_name: The Gemini model name
            tools: LangChain tools to include in the cache

        Returns:
            Cache name string for use with ChatGoogleGenerativeAI(cached_content=...),
            or None on any failure.
        """
        try:
            prompt = get_static_prompt_for_profile(profile.value)
            tool_names = [t.name for t in tools]
            content_hash = _compute_content_hash(prompt, tool_names)
            cache_key = f"{profile.value}:{model_name}"

            with self._lock:
                entry = self._caches.get(cache_key)
                now = time.time()

                # Check if existing cache is valid and not expiring soon
                if entry and entry.content_hash == content_hash:
                    buffer = Config.CONTEXT_CACHE_RENEWAL_BUFFER_SECONDS
                    if entry.expires_at > now + buffer:
                        logger.debug(
                            "Context cache hit",
                            extra={
                                "cache_key": cache_key,
                                "expires_in": int(entry.expires_at - now),
                            },
                        )
                        return entry.cache_name

                # Need to create a new cache
                cache_name = self._create_cache(profile, model_name, prompt, tools)
                if cache_name:
                    ttl = Config.CONTEXT_CACHE_TTL_SECONDS
                    self._caches[cache_key] = CacheEntry(
                        cache_name=cache_name,
                        content_hash=content_hash,
                        created_at=now,
                        expires_at=now + ttl,
                    )
                    return cache_name

                return None
        except Exception:
            logger.warning("Context cache get_or_create failed", exc_info=True)
            return None

    def _create_cache(
        self,
        profile: CacheProfile,
        model_name: str,
        prompt: str,
        tools: list[Any],
    ) -> str | None:
        """Create a new cached content via the Gemini API.

        Returns the cache name or None on failure.
        """
        try:
            from google.genai import types
            from langchain_google_genai._function_utils import (
                convert_to_genai_function_declarations,
            )

            client = self._get_client()

            # Convert LangChain tools to google.genai Tool format
            genai_tools = convert_to_genai_function_declarations(tools)

            ttl_seconds = Config.CONTEXT_CACHE_TTL_SECONDS

            result = client.caches.create(
                model=model_name,
                config=types.CreateCachedContentConfig(
                    system_instruction=prompt,
                    tools=genai_tools,
                    ttl=f"{ttl_seconds}s",
                    display_name=f"ai-chatbot-{profile.value}",
                ),
            )

            logger.info(
                "Context cache created",
                extra={
                    "cache_name": result.name,
                    "profile": profile.value,
                    "model": model_name,
                    "ttl_seconds": ttl_seconds,
                },
            )
            return str(result.name)
        except Exception:
            logger.warning("Context cache creation failed", exc_info=True)
            return None


# Module-level singleton
_manager = ContextCacheManager()


def get_cached_content_name(
    profile: CacheProfile,
    model_name: str,
    tools: list[Any],
) -> str | None:
    """Convenience function to get a cached content name.

    Returns None if:
    - Feature is disabled (CONTEXT_CACHE_ENABLED=false)
    - Cache creation fails (falls back to uncached path)

    Args:
        profile: Which cache profile to use
        model_name: The Gemini model name
        tools: LangChain tools to include

    Returns:
        Cache name string or None
    """
    if not Config.CONTEXT_CACHE_ENABLED:
        return None

    return _manager.get_or_create(profile, model_name, tools)
