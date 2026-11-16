"""Repeated side calls to Gemini reuse one client instead of building one each.

Every ChatGoogleGenerativeAI or genai.Client builds httpx clients with their
own TLS contexts; after a request they sit in reference cycles, so ~0.8 MB per
call waited for a full garbage collection that busy workers almost never ran
(Oct 16 2026: the freshness gate alone builds one on every regular turn).
"""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import httpx
import httpx2
import pytest
from google import genai

from src.agent import (
    compaction,
    freshness,
    gemini_clients,
    grounding_check,
    instructions_review,
    program_review,
    title,
)
from src.agent.deep_research import writer
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

    def answer2(_transport: httpx2.HTTPTransport, request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=_REPLY, request=request)

    # google-genai 3.x sends through httpx2 (pydantic's httpx fork) when it is
    # installed, which it pulls in; plain httpx stays for other callers
    with (
        patch.object(genai.Client, "__init__", counting_init),
        patch.object(httpx.HTTPTransport, "handle_request", answer),
        patch.object(httpx2.HTTPTransport, "handle_request", answer2),
        patch.object(Config, "GEMINI_API_KEY", "test-key"),
    ):
        yield built


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda: freshness._ask_gate("Who won yesterday?", "", 0), id="freshness-gate"),
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


@contextmanager
def _request_bodies() -> Iterator[list[dict[str, Any]]]:
    """The JSON bodies sent to Gemini while it is answered locally."""
    bodies: list[dict[str, Any]] = []

    def answer(_transport: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.read() or b"{}"))
        return httpx.Response(200, json=_REPLY, request=request)

    def answer2(_transport: httpx2.HTTPTransport, request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.read() or b"{}"))
        return httpx2.Response(200, json=_REPLY, request=request)

    with (
        patch.object(httpx.HTTPTransport, "handle_request", answer),
        patch.object(httpx2.HTTPTransport, "handle_request", answer2),
        patch.object(Config, "GEMINI_API_KEY", "test-key"),
    ):
        yield bodies


def _thinking_level(body: dict[str, Any]) -> str | None:
    thinking = body.get("generationConfig", {}).get("thinkingConfig", {})
    level = thinking.get("thinkingLevel") or thinking.get("thinking_level")
    return str(level).lower() if level else None


# Side calls on Hydrogen ran at the API default (high) thinking until Nov 16
# 2026; each now sends its own configured level
@pytest.mark.parametrize(
    ("call", "setting"),
    [
        pytest.param(
            lambda: program_review._invoke("Review."),
            "PROGRAM_REVIEW_THINKING_LEVEL",
            id="program-review",
        ),
        pytest.param(
            lambda: instructions_review._invoke("Review."),
            "INSTRUCTIONS_REVIEW_THINKING_LEVEL",
            id="instructions-review",
        ),
        pytest.param(
            lambda: writer.extract_followups("A report."),
            "DEEP_RESEARCH_FOLLOWUP_THINKING_LEVEL",
            id="deep-research-followups",
        ),
    ],
)
def test_side_calls_send_their_thinking_level(call: Callable[[], object], setting: str) -> None:
    with _request_bodies() as bodies, patch.object(Config, setting, "low"):
        call()
    assert bodies
    assert _thinking_level(bodies[-1]) == "low"


def test_chat_model_without_a_level_sends_none() -> None:
    with _request_bodies() as bodies:
        gemini_clients.chat_model("gemini-4-hydrogen").invoke("Hi")
    assert _thinking_level(bodies[-1]) is None
