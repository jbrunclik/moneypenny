"""Process-wide Gemini clients for the side calls made outside the agent graph.

Every ChatGoogleGenerativeAI and genai.Client builds httpx clients with their
own TLS contexts (three CA-bundle loads each). After a request they sit in
reference cycles, so a client built per call kept ~0.8 MB of native memory
until a full garbage collection, which busy workers almost never ran (Oct 16
2026: the freshness gate built one on every regular turn). Both are safe to
share between threads; request timeouts are applied per call, so a cached
model behaves like a fresh one.
"""

from functools import cache, lru_cache

from google import genai
from google.genai import types
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import Config

# Distinct (model, temperature, timeout, retries) settings in use; a few each
_MAX_CACHED_MODELS = 32


@cache
def shared_genai_client() -> genai.Client:
    """The google.genai client for direct SDK calls (summaries, images, files)."""
    return genai.Client(
        api_key=Config.GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=int(Config.GEMINI_REQUEST_TIMEOUT_SECONDS * 1000)),
    )


@lru_cache(maxsize=_MAX_CACHED_MODELS)
def chat_model(
    model: str,
    *,
    temperature: float | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
) -> ChatGoogleGenerativeAI:
    """One LangChain chat model per setting. Unset arguments keep the
    library defaults (e.g. no temperature at all for Gemini 3); the timeout
    defaults to GEMINI_REQUEST_TIMEOUT_SECONDS."""
    optional = {"temperature": temperature, "max_retries": max_retries}
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=Config.GEMINI_API_KEY,
        timeout=timeout or Config.GEMINI_REQUEST_TIMEOUT_SECONDS,
        **{k: v for k, v in optional.items() if v is not None},
    )


def clear_cached_clients() -> None:
    """Drop the cached clients (tests, or after the API key changes)."""
    shared_genai_client.cache_clear()
    chat_model.cache_clear()
