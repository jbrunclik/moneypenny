"""A model call that fails after it streamed text is not retried: the retry
re-streamed the reply while the failed attempt's text stayed on screen and
in the saved reply, so it appeared twice (Nov 15 2026 audit)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_google_genai.chat_models import GoogleAPIError

from src.agent import chat_node
from src.agent.retry import PartialStreamError, with_retry


class _Model:
    """Streams `tokens` through the call's callbacks, then fails or answers."""

    def __init__(self, tokens: list[str], fail: bool) -> None:
        self.tokens, self.fail, self.calls = tokens, fail, 0

    def invoke(self, messages: list[Any], config: dict[str, Any]) -> AIMessage:
        self.calls += 1
        for handler in config["callbacks"]:
            for token in self.tokens:
                handler.on_llm_new_token(token, run_id=uuid4())
        if self.fail:
            raise GoogleAPIError(code=500, response_json={"error": {"status": "INTERNAL"}})
        return AIMessage(content="ok")


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.agent.retry.time.sleep", lambda _s: None)


def test_a_failure_after_streamed_text_is_not_retried() -> None:
    model = _Model(["Hello"], fail=True)
    with pytest.raises(PartialStreamError):
        with_retry(chat_node._invoke_model)(model, [], None)
    assert model.calls == 1


def test_a_failure_before_any_text_is_retried() -> None:
    model = _Model([], fail=True)
    with pytest.raises(GoogleAPIError):
        with_retry(chat_node._invoke_model, max_retries=2)(model, [], None)
    assert model.calls == 3


def test_an_empty_token_does_not_count_as_streamed_text() -> None:
    model = _Model([""], fail=True)
    with pytest.raises(GoogleAPIError):
        with_retry(chat_node._invoke_model, max_retries=1)(model, [], None)
    assert model.calls == 2
