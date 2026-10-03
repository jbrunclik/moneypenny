"""Unit tests for the post-answer grounding check (src/agent/grounding_check.py)."""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent import grounding_check
from src.agent.grounding_annotations import ClaimVerdict, GroundingVerdict
from src.agent.grounding_check import check_grounding, format_sources, should_check
from src.agent.source_pages import SourcePage
from src.config import Config


def _tool(name: str, content: object, status: str = "success") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=f"id-{name}", name=name, status=status)


def _research_turn(text: str) -> list[Any]:
    payload = json.dumps(
        {"sources": [{"title": "Bike Prague", "url": "https://bike.cz", "content": text}]}
    )
    return [
        AIMessage(content="", tool_calls=[{"name": "research", "args": {}, "id": "r1"}]),
        ToolMessage(content=payload, tool_call_id="r1", name="research"),
    ]


_USAGE = {"model": "m", "input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 0}
_WEB_TURN = _research_turn("Kolo Brompton C Line stojí 32 990 Kč u Bike Prague.")
_ANSWER = "Brompton koupíte u Bike Prague (32 990 Kč) nebo ve VeloRama za 29 990 Kč."


@pytest.fixture
def fake_verifier(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace the LLM call; tests set .return_value or .side_effect."""
    monkeypatch.setattr(Config, "GROUNDING_CHECK_ENABLED", True)
    fake = MagicMock(return_value=(GroundingVerdict(), _USAGE))
    monkeypatch.setattr(grounding_check, "_run_verifier", fake)
    return fake


class TestFormatSources:
    def test_numbers_pages_and_appends_uncited_text(self) -> None:
        text = format_sources(
            [SourcePage("A", "https://a.cz", "alpha"), SourcePage("B", "https://b.cz", "beta")],
            "snippet text",
            1000,
        )

        assert text.startswith("[1] A (https://a.cz)\nalpha\n\n[2] B (https://b.cz)\nbeta")
        assert text.endswith("UNNUMBERED (may support a claim, cannot be cited):\nsnippet text")

    def test_cap_is_shared_between_pages(self) -> None:
        text = format_sources(
            [SourcePage("A", "u", "a" * 500), SourcePage("B", "v", "b" * 500)], "", 200
        )

        assert text.count("a") <= 100
        assert text.count("b") <= 100


class TestCheckGrounding:
    def test_returns_validated_annotations_and_summary(self, fake_verifier: MagicMock) -> None:
        fake_verifier.return_value = (
            GroundingVerdict(
                unsupported=[
                    ClaimVerdict(quote="VeloRama", verdict="not_found", reason="Ve zdroji není.")
                ],
                supported=[
                    ClaimVerdict(
                        quote="Bike Prague",
                        verdict="supported",
                        source=1,
                        source_quote="u Bike Prague",
                    )
                ],
            ),
            _USAGE,
        )

        outcome = check_grounding(_ANSWER, _WEB_TURN)

        assert [a["verdict"] for a in outcome.annotations] == ["supported", "not_found"]
        assert outcome.summary == {"checked": True, "source_count": 1}
        assert outcome.usage == _USAGE

    def test_problem_claims_survive_the_claim_cap(
        self, fake_verifier: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Unsupported claims come first so a long supported list never pushes
        # them past GROUNDING_CHECK_MAX_CLAIMS (Oct 2026 eval: recall 71% -> 89%
        # with the problems-first schema)
        monkeypatch.setattr(Config, "GROUNDING_CHECK_MAX_CLAIMS", 1)
        fake_verifier.return_value = (
            GroundingVerdict(
                unsupported=[ClaimVerdict(quote="VeloRama", verdict="not_found")],
                supported=[
                    ClaimVerdict(
                        quote="Bike Prague",
                        verdict="supported",
                        source=1,
                        source_quote="Bike Prague",
                    )
                ],
            ),
            _USAGE,
        )

        outcome = check_grounding(_ANSWER, _WEB_TURN)

        assert [a["quote"] for a in outcome.annotations] == ["VeloRama"]

    def test_prompt_carries_numbered_pages(self, fake_verifier: MagicMock) -> None:
        check_grounding(_ANSWER, _WEB_TURN)

        sources_arg = fake_verifier.call_args.args[1]
        assert sources_arg.startswith("[1] Bike Prague (https://bike.cz)")

    def test_should_check_matches_check_grounding_skips(self, fake_verifier: MagicMock) -> None:
        assert should_check(_ANSWER, _WEB_TURN)
        assert not should_check(_ANSWER, _WEB_TURN, "user")
        assert not should_check("", _WEB_TURN)
        assert not should_check(_ANSWER, [_tool("execute_code", "42")])

    def test_unparsed_web_text_still_gets_checked(self, fake_verifier: MagicMock) -> None:
        check_grounding(_ANSWER, [_tool("web_search", "Shop A sells it for 100 CZK")])

        assert "Shop A sells it for 100 CZK" in fake_verifier.call_args.args[1]

    @pytest.mark.parametrize(
        ("answer", "messages", "stop_reason"),
        [
            ("", _WEB_TURN, None),
            (_ANSWER, _WEB_TURN, "user"),
            (_ANSWER, [_tool("execute_code", "42")], None),
        ],
    )
    def test_skips_without_calling_the_verifier(
        self,
        fake_verifier: MagicMock,
        answer: str,
        messages: list[Any],
        stop_reason: str | None,
    ) -> None:
        outcome = check_grounding(answer, messages, stop_reason)

        assert outcome.annotations == []
        assert outcome.usage is None
        fake_verifier.assert_not_called()

    def test_disabled_skips(
        self, fake_verifier: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Config, "GROUNDING_CHECK_ENABLED", False)

        assert check_grounding(_ANSWER, _WEB_TURN).annotations == []
        fake_verifier.assert_not_called()

    def test_skips_inside_a_delegate_subagent(self, fake_verifier: MagicMock) -> None:
        # The parent turn's answer is what the user sees; checking the
        # subagent's digest cost an unrecorded call
        from src.agent.tools.delegate import _in_delegate

        token = _in_delegate.set(True)
        try:
            outcome = check_grounding(_ANSWER, _WEB_TURN)
        finally:
            _in_delegate.reset(token)

        assert outcome.annotations == []
        fake_verifier.assert_not_called()

    def test_verifier_error_fails_open(self, fake_verifier: MagicMock) -> None:
        fake_verifier.side_effect = TimeoutError("deadline exceeded")

        outcome = check_grounding(_ANSWER, _WEB_TURN)

        assert outcome.annotations == []
        assert outcome.summary is None
        assert outcome.usage is None

    def test_schema_miss_keeps_usage(self, fake_verifier: MagicMock) -> None:
        usage = {"model": "m", "input_tokens": 900, "output_tokens": 5, "cached_input_tokens": 0}
        fake_verifier.return_value = (None, usage)

        outcome = check_grounding(_ANSWER, _WEB_TURN)

        assert outcome.annotations == []
        assert outcome.summary is None
        assert outcome.usage == usage


class TestRunVerifier:
    def test_builds_structured_call_and_reads_usage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        raw = MagicMock(
            usage_metadata={
                "input_tokens": 120,
                "output_tokens": 8,
                "input_token_details": {"cache_read": 20},
            }
        )
        structured = MagicMock()
        structured.invoke.return_value = {
            "raw": raw,
            "parsed": GroundingVerdict(
                unsupported=[ClaimVerdict(quote="VeloRama", verdict="not_found")]
            ),
            "parsing_error": None,
        }
        model = MagicMock()
        model.with_structured_output.return_value = structured
        llm_cls = MagicMock(return_value=model)
        monkeypatch.setattr(grounding_check, "ChatGoogleGenerativeAI", llm_cls)

        verdict, usage = grounding_check._run_verifier(
            "the answer", "the sources", "the known facts"
        )

        kwargs = llm_cls.call_args.kwargs
        assert kwargs["model"] == Config.GROUNDING_CHECK_MODEL
        assert kwargs["temperature"] == 0
        assert kwargs["timeout"] == Config.GROUNDING_CHECK_TIMEOUT_SECONDS
        assert kwargs["max_retries"] == 0
        model.with_structured_output.assert_called_once_with(GroundingVerdict, include_raw=True)
        prompt = structured.invoke.call_args.args[0]
        assert "the answer" in prompt
        assert "the sources" in prompt
        assert "the known facts" in prompt
        assert verdict is not None
        assert verdict.unsupported[0].quote == "VeloRama"
        assert usage == {
            "model": Config.GROUNDING_CHECK_MODEL,
            "input_tokens": 120,
            "output_tokens": 8,
            "cached_input_tokens": 20,
        }

    def test_timeout_respects_the_api_minimum(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The Gemini API rejects deadlines under 10 s with 400 INVALID_ARGUMENT
        # (seen live, Oct 2026): a lower setting would fail every check
        monkeypatch.setattr(Config, "GROUNDING_CHECK_TIMEOUT_SECONDS", 8.0)
        llm_cls = MagicMock()
        llm_cls.return_value.with_structured_output.return_value.invoke.return_value = {
            "raw": MagicMock(usage_metadata={}),
            "parsed": None,
        }
        monkeypatch.setattr(grounding_check, "ChatGoogleGenerativeAI", llm_cls)

        grounding_check._run_verifier("a", "s", "k")

        assert llm_cls.call_args.kwargs["timeout"] == 10


class TestKnownFacts:
    """Facts the answer may state without a web source: today's date and what
    the user said. Without them the verifier flagged "2. 10." (today, from the
    system prompt) under a fully sourced answer (Oct 2026 eval)."""

    def test_today_and_the_last_user_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from datetime import datetime

        monkeypatch.setattr(grounding_check, "_now", lambda: datetime(2026, 10, 2, 13, 1))
        messages = [
            HumanMessage(content="earlier question"),
            AIMessage(content="earlier answer"),
            HumanMessage(content=[{"type": "text", "text": "jaky je kurz eura?"}]),
            _tool("research", "CNB: 24,465"),
        ]

        known = grounding_check.known_facts(messages)

        assert "Friday 2026-10-02" in known
        assert "jaky je kurz eura?" in known
        assert "earlier question" not in known

    def test_non_web_tool_results_are_known(self) -> None:
        # Review finding: a meeting time from the calendar tool is not a web
        # fact, but the answer may state it - it must not be flagged
        messages = [
            HumanMessage(content="restaurace u mé schůzky?"),
            _tool("google_calendar", '{"events": [{"start": "19:00", "location": "Karlín"}]}'),
            _tool("web_search", "Restaurant X in Karlín"),
            _tool("garmin_connect", "Error: expired", status="error"),
        ]

        known = grounding_check.known_facts(messages)

        assert "19:00" in known
        assert "Karlín" in known
        assert "Restaurant X" not in known  # web results are the SOURCES, not known
        assert "expired" not in known

    def test_check_grounding_passes_known_facts(self, fake_verifier: MagicMock) -> None:
        check_grounding(_ANSWER, [HumanMessage(content="kde koupit brompton"), *_WEB_TURN])

        assert "kde koupit brompton" in fake_verifier.call_args.args[2]


class TestPrompt:
    def test_prompt_excludes_own_plan_and_geography(self) -> None:
        from src.agent.prompt_texts.grounding import GROUNDING_CHECK_PROMPT

        prompt = GROUNDING_CHECK_PROMPT.casefold()
        assert "own plan" in prompt
        assert "well-known places" in prompt

    def test_prompt_names_the_four_verdicts(self) -> None:
        from src.agent.prompt_texts.grounding import GROUNDING_CHECK_PROMPT

        for verdict in ("supported", "partial", "contradicted", "not_found"):
            assert f"- {verdict}:" in GROUNDING_CHECK_PROMPT

    def test_prompt_asks_for_unique_quotes(self) -> None:
        # A repeated phrase can't be placed; the server drops conflicting ones
        from src.agent.prompt_texts.grounding import GROUNDING_CHECK_PROMPT

        assert "more than once" in GROUNDING_CHECK_PROMPT
