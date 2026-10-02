"""Unit tests for the post-answer grounding check (src/agent/grounding_check.py)."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent import grounding_check
from src.agent.grounding_check import (
    GroundingVerdict,
    UnverifiedItem,
    append_unverified_note,
    collect_web_sources,
    find_unverified,
)
from src.config import Config


def _tool(name: str, content: object, status: str = "success") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=f"id-{name}", name=name, status=status)


class TestCollectWebSources:
    def test_only_successful_web_tool_results_count(self) -> None:
        messages = [
            HumanMessage(content="where to buy"),
            _tool("web_search", "Shop A sells it for 100 CZK"),
            _tool("garmin_connect", '{"hrv": 41}'),
            _tool("fetch_url", "Error: 404", status="error"),
            AIMessage(content="answer"),
        ]

        assert collect_web_sources(messages, 1000) == "Shop A sells it for 100 CZK"

    def test_no_web_results_gives_empty_string(self) -> None:
        assert collect_web_sources([_tool("execute_code", "42")], 1000) == ""

    def test_multimodal_content_contributes_its_text_parts(self) -> None:
        content = [
            {"type": "text", "text": "PDF page: open 9-17"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]

        assert collect_web_sources([_tool("fetch_url", content)], 1000) == "PDF page: open 9-17"

    def test_cap_keeps_the_most_recent_results(self) -> None:
        messages = [_tool("web_search", "old " * 50), _tool("research", "newest result")]

        sources = collect_web_sources(messages, 20)

        # Filled newest-first (13 chars), the older result gets the remaining 7;
        # kept parts come back in original order
        assert sources == "old old" + "\n\n---\n\n" + "newest result"

    def test_single_result_longer_than_cap_is_truncated_not_dropped(self) -> None:
        sources = collect_web_sources([_tool("research", "x" * 500)], 100)

        assert sources == "x" * 100


class TestAppendUnverifiedNote:
    def test_no_items_leaves_answer_unchanged(self) -> None:
        assert append_unverified_note("Answer.", [], "cs") == "Answer."

    def test_czech_note(self) -> None:
        result = append_unverified_note("Odpověď.\n", ["VeloRama", "12 990 Kč"], "cs")

        assert result == (
            "Odpověď.\n\n_Neověřeno ve zdrojích, které jsem teď četl: VeloRama, 12 990 Kč._"
        )

    def test_english_note_for_other_and_unknown_languages(self) -> None:
        for language in ("en", "de", None):
            result = append_unverified_note("Answer.", ["VeloRama"], language)

            assert result == (
                "Answer.\n\n_Not confirmed in the sources I read for this answer: VeloRama._"
            )


def _verdict(*items: tuple[str, str]) -> GroundingVerdict:
    return GroundingVerdict(
        unsupported=[UnverifiedItem(text=t, kind=k) for t, k in items]  # type: ignore[arg-type]
    )


_USAGE = {"model": "m", "input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 0}


@pytest.fixture
def fake_verifier(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace the LLM call; tests set .return_value or .side_effect."""
    monkeypatch.setattr(Config, "GROUNDING_CHECK_ENABLED", True)
    fake = MagicMock(return_value=(_verdict(), _USAGE))
    monkeypatch.setattr(grounding_check, "_run_verifier", fake)
    return fake


_WEB_TURN = [_tool("research", "Kolo Brompton C Line stojí 32 990 Kč u Bike Prague.")]
_ANSWER = "Brompton koupíte u Bike Prague (32 990 Kč) nebo ve VeloRama za 29 990 Kč."


class TestFindUnverified:
    def test_flags_items_the_verifier_returns(self, fake_verifier: MagicMock) -> None:
        fake_verifier.return_value = (
            _verdict(("VeloRama", "shop"), ("29 990 Kč", "price")),
            _USAGE,
        )

        result = find_unverified(_ANSWER, _WEB_TURN)

        assert result.items == ["VeloRama", "29 990 Kč"]
        assert result.kinds == ["shop", "price"]
        assert result.usage == _USAGE

    def test_drops_items_not_in_the_answer(self, fake_verifier: MagicMock) -> None:
        # The verifier paraphrased or invented an item: the note must only
        # ever name things the answer actually says
        fake_verifier.return_value = (
            _verdict(("Velo Rama s.r.o.", "shop"), ("velorama", "shop")),
            None,
        )

        assert find_unverified(_ANSWER, _WEB_TURN).items == ["velorama"]

    def test_dedupes_and_caps_items(
        self, fake_verifier: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Config, "GROUNDING_CHECK_MAX_ITEMS", 2)
        fake_verifier.return_value = (
            _verdict(
                ("VeloRama", "shop"),
                ("VeloRama", "shop"),
                ("29 990 Kč", "price"),
                ("Bike Prague", "shop"),
            ),
            None,
        )

        assert find_unverified(_ANSWER, _WEB_TURN).items == ["VeloRama", "29 990 Kč"]

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
        result = find_unverified(answer, messages, stop_reason)

        assert result.items == []
        assert result.usage is None
        fake_verifier.assert_not_called()

    def test_disabled_skips(
        self, fake_verifier: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Config, "GROUNDING_CHECK_ENABLED", False)

        assert find_unverified(_ANSWER, _WEB_TURN).items == []
        fake_verifier.assert_not_called()

    def test_verifier_error_fails_open(self, fake_verifier: MagicMock) -> None:
        fake_verifier.side_effect = TimeoutError("deadline exceeded")

        result = find_unverified(_ANSWER, _WEB_TURN)

        assert result.items == []
        assert result.usage is None

    def test_keeps_literal_false_claims_capped(
        self, fake_verifier: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Config, "GROUNDING_CHECK_MAX_FALSE_CLAIMS", 1)
        answer = _ANSWER + " Ceny jsem ověřil na webu VeloRama. Sklad potvrzen."
        fake_verifier.return_value = (
            GroundingVerdict(
                unsupported=[],
                false_claims=[
                    "Ceny jsem ověřil na webu VeloRama.",
                    "Sklad potvrzen.",
                    "A claim the answer never made.",
                ],
            ),
            _USAGE,
        )

        result = find_unverified(answer, _WEB_TURN)

        assert result.false_claims == ["Ceny jsem ověřil na webu VeloRama."]

    def test_drops_false_claims_not_in_the_answer(self, fake_verifier: MagicMock) -> None:
        fake_verifier.return_value = (
            GroundingVerdict(unsupported=[], false_claims=["Invented sentence."]),
            _USAGE,
        )

        assert find_unverified(_ANSWER, _WEB_TURN).false_claims == []

    def test_drops_items_over_the_length_cap(
        self, fake_verifier: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A whole sentence came back as an "item" in a live probe (Oct 2026);
        # only false_claims may be sentences
        monkeypatch.setattr(Config, "GROUNDING_CHECK_MAX_ITEM_CHARS", 20)
        long_item = "Brompton koupíte u Bike Prague (32 990 Kč)"
        fake_verifier.return_value = (_verdict((long_item, "other"), ("VeloRama", "shop")), _USAGE)

        assert find_unverified(_ANSWER, _WEB_TURN).items == ["VeloRama"]

    def test_schema_miss_keeps_usage(self, fake_verifier: MagicMock) -> None:
        usage = {"model": "m", "input_tokens": 900, "output_tokens": 5, "cached_input_tokens": 0}
        fake_verifier.return_value = (None, usage)

        result = find_unverified(_ANSWER, _WEB_TURN)

        assert result.items == []
        assert result.usage == usage


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
            "parsed": _verdict(("VeloRama", "shop")),
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
        assert verdict.unsupported[0].text == "VeloRama"
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

    def test_find_unverified_passes_known_facts(self, fake_verifier: MagicMock) -> None:
        find_unverified(_ANSWER, [HumanMessage(content="kde koupit brompton"), *_WEB_TURN])

        assert "kde koupit brompton" in fake_verifier.call_args.args[2]
