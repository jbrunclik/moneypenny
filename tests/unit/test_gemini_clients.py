"""Repeated side calls to Gemini reuse one client instead of building one each.

Every ChatGoogleGenerativeAI or genai.Client builds httpx clients with their
own TLS contexts; after a request they sit in reference cycles, so ~0.8 MB per
call waited for a full garbage collection that busy workers almost never ran
(Oct 16 2026: the freshness gate alone builds one on every regular turn).
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from google import genai

from src.agent import compaction, freshness, gemini_clients, grounding_check, title
from src.config import Config

_REPLY = {
    "candidates": [
        {"content": {"role": "model", "parts": [{"text": "📝 A title"}]}, "finishReason": "STOP"}
    ],
    "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
}


@pytest.fixture(autouse=True)
def _fresh_caches() -> Iterator[None]:
    gemini_clients.clear_cached_clients()
    yield
    gemini_clients.clear_cached_clients()


@contextmanager
def _clients_built() -> Iterator[list[None]]:
    """Count genai.Client constructions while Gemini is answered locally."""
    built: list[None] = []
    real_init = genai.Client.__init__

    def counting_init(self: genai.Client, *args: Any, **kwargs: Any) -> None:
        built.append(None)
        real_init(self, *args, **kwargs)

    def answer(_transport: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_REPLY, request=request)

    with (
        patch.object(genai.Client, "__init__", counting_init),
        patch.object(httpx.HTTPTransport, "handle_request", answer),
        patch.object(Config, "GEMINI_API_KEY", "test-key"),
    ):
        yield built


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda: freshness._ask_gate("Who won yesterday?", ""), id="freshness-gate"),
        pytest.param(
            lambda: grounding_check._run_verifier("An answer.", "Sources.", ""), id="grounding"
        ),
        pytest.param(lambda: title.generate_title("Hi there", "Hello!"), id="title"),
        pytest.param(lambda: compaction.run_summary_model("Summarise this."), id="compaction"),
    ],
)
def test_repeated_calls_build_one_client(call: Callable[[], object]) -> None:
    with _clients_built() as built:
        for _ in range(3):
            call()
    assert len(built) <= 1
