"""The freshness gate (src/agent/freshness.py).

Oct 2026: a September keynote and a Prague council reshuffle were answered
from training data - no tool at all on most follow-ups, and only after the user
pushed back did the agent look anything up. The prompt's "ALWAYS use web tools
for recent events" was measured to be ignored, so a small model decides before
the turn whether the answer needs fresh facts, and the lookup runs first.
"""

import json
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agent import freshness, gemini_clients
from src.config import Config


def _verdict_model(verdict: Any, *, raises: Exception | None = None) -> MagicMock:
    raw = MagicMock(usage_metadata={"input_tokens": 300, "output_tokens": 20})
    structured = MagicMock()
    if raises:
        structured.invoke.side_effect = raises
    else:
        structured.invoke.return_value = {"raw": raw, "parsed": verdict}
    model = MagicMock()
    model.with_structured_output.return_value = structured
    return model


_TURN = [
    SystemMessage(content="system"),
    HumanMessage(content="Sleduju zářijovou keynote, jak funguje Siri AI?"),
    AIMessage(content='Siri AI běží na třívrstvém modelu…<!-- MSG_CONTEXT: {"x": 1} -->'),
    HumanMessage(content="Jaký externí modely maj?"),
]


@pytest.fixture(autouse=True)
def _enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "FRESHNESS_GATE_ENABLED", True)
    monkeypatch.setattr(freshness, "_today", lambda: date(2026, 10, 10))


class TestLatestExchange:
    def test_last_user_message_and_the_reply_before_it_without_metadata(self) -> None:
        user, previous = freshness.latest_exchange(_TURN)
        assert user == "Jaký externí modely maj?"
        assert previous.startswith("Siri AI běží")
        assert "MSG_CONTEXT" not in previous

    def test_multimodal_content_keeps_the_text(self) -> None:
        turn = [
            HumanMessage(
                content=[{"type": "text", "text": "Co je na fotce?"}, {"type": "image_url"}]
            )
        ]
        assert freshness.latest_exchange(turn) == ("Co je na fotce?", "")


class TestDecide:
    def test_a_lookup_comes_with_dated_queries_and_priced_usage(self) -> None:
        verdict = freshness.GateVerdict(
            lookup=True,
            queries=["Apple Siri AI external models září 2026", "a", "b", "c"],
            reason="keynote follow-up",
        )
        with patch.object(
            gemini_clients, "ChatGoogleGenerativeAI", return_value=_verdict_model(verdict)
        ):
            decision = freshness.decide_freshness(_TURN)
        assert decision.lookup is True
        assert decision.queries[0] == "Apple Siri AI external models září 2026"
        assert len(decision.queries) <= Config.FRESHNESS_GATE_MAX_QUERIES
        assert decision.usage == {
            "model": Config.FRESHNESS_GATE_MODEL,
            "input_tokens": 300,
            "output_tokens": 20,
            "cached_input_tokens": 0,
        }

    def test_the_prompt_is_dated_and_carries_the_exchange(self) -> None:
        model = _verdict_model(freshness.GateVerdict(lookup=False))
        with patch.object(gemini_clients, "ChatGoogleGenerativeAI", return_value=model):
            freshness.decide_freshness(_TURN)
        prompt = model.with_structured_output.return_value.invoke.call_args.args[0]
        assert "TODAY: 2026-10-10" in prompt
        assert "Jaký externí modely maj?" in prompt and "Siri AI běží" in prompt

    def test_fails_open_on_any_error(self) -> None:
        model = _verdict_model(None, raises=TimeoutError("slow"))
        with patch.object(gemini_clients, "ChatGoogleGenerativeAI", return_value=model):
            assert freshness.decide_freshness(_TURN).lookup is False

    def test_a_lookup_without_queries_is_no_lookup(self) -> None:
        verdict = freshness.GateVerdict(lookup=True, queries=[" "])
        with patch.object(
            gemini_clients, "ChatGoogleGenerativeAI", return_value=_verdict_model(verdict)
        ):
            assert freshness.decide_freshness(_TURN).lookup is False

    def test_disabled_makes_no_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Config, "FRESHNESS_GATE_ENABLED", False)
        with patch.object(gemini_clients, "ChatGoogleGenerativeAI") as model_class:
            assert freshness.decide_freshness(_TURN).lookup is False
        model_class.assert_not_called()


class TestThinking:
    """Oct 2026: low thinking halved plain turns (12.9 -> 5.6 s) but skipped
    skills and delegation on hard ones, so the gate - already one call before
    every turn - says which turns need full thinking."""

    def _decide(self, verdict: freshness.GateVerdict) -> freshness.FreshnessDecision:
        with patch.object(
            gemini_clients, "ChatGoogleGenerativeAI", return_value=_verdict_model(verdict)
        ):
            return freshness.decide_freshness(_TURN)

    def test_an_easy_turn_runs_light(self) -> None:
        assert (
            self._decide(freshness.GateVerdict(lookup=False, think_hard=False)).think_hard is False
        )

    def test_a_hard_turn_keeps_full_thinking(self) -> None:
        assert self._decide(freshness.GateVerdict(lookup=False, think_hard=True)).think_hard is True

    def test_an_error_keeps_full_thinking(self) -> None:
        model = _verdict_model(None, raises=TimeoutError("slow"))
        with patch.object(gemini_clients, "ChatGoogleGenerativeAI", return_value=model):
            assert freshness.decide_freshness(_TURN).think_hard is True

    def test_an_unparsed_answer_keeps_full_thinking(self) -> None:
        with patch.object(
            gemini_clients, "ChatGoogleGenerativeAI", return_value=_verdict_model(None)
        ):
            assert freshness.decide_freshness(_TURN).think_hard is True

    def test_a_timeout_keeps_full_thinking(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import time

        monkeypatch.setattr(Config, "FRESHNESS_GATE_TIMEOUT_SECONDS", 0.1)

        def slow(*_args: Any) -> Any:
            time.sleep(1)  # a gate call slower than its cap; nothing to poll
            return freshness.GateVerdict(lookup=False, think_hard=False), None

        with patch.object(freshness, "_ask_gate", side_effect=slow):
            assert freshness.decide_freshness(_TURN).think_hard is True

    def test_a_disabled_gate_keeps_full_thinking(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Config, "FRESHNESS_GATE_ENABLED", False)
        assert freshness.decide_freshness(_TURN).think_hard is True


class TestPrefetch:
    def test_runs_research_and_returns_the_call_and_its_result(self) -> None:
        decision = freshness.FreshnessDecision(lookup=True, queries=["q1 září 2026"], reason="r")
        body = json.dumps({"sources": [{"url": "https://a.example"}], "_full_result": {"x": 1}})
        with patch.object(freshness, "_run_research", return_value=body) as research:
            call, result = freshness.prefetch_messages(decision, "Jaký externí modely maj?")

        research.assert_called_once_with(
            {"question": "Jaký externí modely maj?", "queries": ["q1 září 2026"]}
        )
        assert isinstance(call, AIMessage) and call.tool_calls[0]["name"] == "research"
        assert isinstance(result, ToolMessage) and result.name == "research"
        assert result.tool_call_id == call.tool_calls[0]["id"]
        assert "_full_result" not in str(result.content)


class TestDeadlines:
    def test_the_api_deadline_respects_gemini_minimum(self) -> None:
        from src.constants import GEMINI_MIN_REQUEST_DEADLINE_SECONDS

        with patch.object(
            gemini_clients,
            "ChatGoogleGenerativeAI",
            return_value=_verdict_model(freshness.GateVerdict(lookup=False)),
        ) as model_class:
            freshness.decide_freshness(_TURN)
        assert model_class.call_args.kwargs["timeout"] >= GEMINI_MIN_REQUEST_DEADLINE_SECONDS

    def test_a_slow_gate_is_cut_off_at_its_own_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import time

        monkeypatch.setattr(Config, "FRESHNESS_GATE_TIMEOUT_SECONDS", 0.2)

        def slow(*_args: Any) -> Any:
            time.sleep(2)  # a gate call slower than its cap; nothing to poll
            return freshness.GateVerdict(lookup=True, queries=["q"]), None

        started = time.monotonic()
        with patch.object(freshness, "_ask_gate", side_effect=slow):
            decision = freshness.decide_freshness(_TURN)
        assert decision.lookup is False
        assert time.monotonic() - started < 1.0


class TestFailedLookup:
    def test_a_failed_lookup_says_to_admit_it_not_to_answer_from_memory(self) -> None:
        decision = freshness.FreshnessDecision(lookup=True, queries=["q 2026"], reason="r")
        body = json.dumps(
            {"error": "All searches failed. Answer from what you know.", "retriable": True}
        )
        with patch.object(freshness, "_run_research", return_value=body):
            _call, result = freshness.prefetch_messages(decision, "Kdo je teď náměstek?")
        content = json.loads(str(result.content))
        assert "could not look up" in content["_freshness"]
        assert "from what you know" not in str(result.content)


class TestDisputes:
    """Pushback: a lookup alone did not stop the agent agreeing with a user who
    was wrong (fresh_pushback_holds 1/3). The disputed turn's research result
    says how to decide."""

    def test_the_gate_reports_a_dispute(self) -> None:
        verdict = freshness.GateVerdict(lookup=True, queries=["q 2026"], disputed=True)
        with patch.object(
            gemini_clients, "ChatGoogleGenerativeAI", return_value=_verdict_model(verdict)
        ):
            assert freshness.decide_freshness(_TURN).disputed is True

    def test_a_disputed_lookup_carries_the_decide_from_sources_note(self) -> None:
        decision = freshness.FreshnessDecision(lookup=True, queries=["q 2026"], disputed=True)
        body = json.dumps({"sources": [{"url": "https://a.example", "content": "x"}]})
        with patch.object(freshness, "_run_research", return_value=body):
            _call, result = freshness.prefetch_messages(decision, "To není pravda")
        note = json.loads(str(result.content))["_dispute"]
        assert "do not apologise" in note and "correct" in note

    def test_no_note_without_a_dispute(self) -> None:
        decision = freshness.FreshnessDecision(lookup=True, queries=["q 2026"])
        body = json.dumps({"sources": []})
        with patch.object(freshness, "_run_research", return_value=body):
            _call, result = freshness.prefetch_messages(decision, "q")
        assert "_dispute" not in str(result.content)
