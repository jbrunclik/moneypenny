"""Unit tests for the post-answer grounding check (src/agent/grounding_check.py)."""

import json
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent import gemini_clients, grounding_check
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

    def test_short_pages_leave_their_share_to_long_ones(self) -> None:
        """A 15k fetch_url page was cut to an equal share while short research
        pages left theirs unused - facts the model read fell off the end."""
        text = format_sources(
            [SourcePage("A", "u", "a" * 100), SourcePage("B", "v", "b" * 900)], "", 600
        )

        assert text.count("a") == 100
        assert text.count("b") == 500

    def test_earlier_verified_claims_outlast_snippets(self, fake_verifier: MagicMock) -> None:
        snippets = json.dumps(
            {"results": [{"title": "S", "url": "https://s.cz", "snippet": "s" * 5000}]}
        )
        messages = [
            *_WEB_TURN,
            AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "w1"}]),
            ToolMessage(content=snippets, tool_call_id="w1", name="web_search"),
        ]
        history = [
            {
                "role": "assistant",
                "content": "x",
                "metadata": {
                    "verified_claims": [
                        {
                            "quote": "Q",
                            "source_quote": "EARLIER",
                            "title": "T",
                            "url": "https://t.cz",
                        }
                    ]
                },
            }
        ]

        with patch.object(Config, "GROUNDING_CHECK_MAX_SOURCE_CHARS", 3000):
            check_grounding(_ANSWER, messages, history=history)

        assert "EARLIER" in fake_verifier.call_args.args[1]


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

        # VeloRama's 29 990 Kč is on no page: the price net marks it too
        assert [(a["verdict"], a["quote"]) for a in outcome.annotations] == [
            ("supported", "Bike Prague"),
            ("not_found", "VeloRama"),
            ("not_found", "29 990 Kč"),
        ]
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
        monkeypatch.setattr(gemini_clients, "ChatGoogleGenerativeAI", llm_cls)

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
        monkeypatch.setattr(gemini_clients, "ChatGoogleGenerativeAI", llm_cls)

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


_IMAGE = {"type": "image", "base64": "aW1n", "mime_type": "image/jpeg"}


class TestUserImages:
    """Oct 2026 prod: a user's poll screenshot (STEM, 10 Oct: STAN 45, ODS 31,
    Piráti 19) was invisible to the verifier, which marked the seat counts
    read off it "contradicted" by a stale 2025 article - and the user's
    "Look it up" on that false flag set off a turn defending a correct figure."""

    def test_images_of_the_latest_user_message(self) -> None:
        old = {"type": "image", "base64": "b2xk", "mime_type": "image/png"}
        messages = [
            HumanMessage(content=[{"type": "text", "text": "earlier"}, old]),
            AIMessage(content="earlier answer"),
            HumanMessage(content=[_IMAGE]),
            *_WEB_TURN,
        ]

        assert grounding_check.user_files(messages) == [_IMAGE]

    def test_text_only_message_has_no_images(self) -> None:
        assert grounding_check.user_files([HumanMessage(content="hi"), *_WEB_TURN]) == []

    def test_known_facts_say_the_images_are_known(self) -> None:
        known = grounding_check.known_facts([HumanMessage(content=[_IMAGE]), *_WEB_TURN])

        assert "attached 1 file" in known

    def test_the_verifier_sees_the_users_images(self, fake_verifier: MagicMock) -> None:
        check_grounding(_ANSWER, [HumanMessage(content=[_IMAGE]), *_WEB_TURN])

        assert _IMAGE in fake_verifier.call_args.kwargs["images"]

    def test_images_ride_in_one_multimodal_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        llm_cls = MagicMock()
        structured = llm_cls.return_value.with_structured_output.return_value
        structured.invoke.return_value = {"raw": MagicMock(usage_metadata={}), "parsed": None}
        monkeypatch.setattr(gemini_clients, "ChatGoogleGenerativeAI", llm_cls)

        grounding_check._run_verifier("the answer", "s", "k", images=[_IMAGE])

        (message,) = structured.invoke.call_args.args[0]
        assert isinstance(message, HumanMessage)
        assert "the answer" in message.content[0]["text"]
        assert message.content[1:] == [_IMAGE]


_PDF = {"type": "image", "base64": "cGRm", "mime_type": "application/pdf"}


def _fetched_pdf_turn() -> list[Any]:
    url = "https://bistro.cz/menu.pdf"
    return [
        AIMessage(content="", tool_calls=[{"name": "fetch_url", "args": {"url": url}, "id": "f1"}]),
        ToolMessage(
            content=[{"type": "text", "text": f"Here is the content from {url}:"}, _PDF],
            tool_call_id="f1",
            name="fetch_url",
        ),
    ]


class TestTurnFiles:
    """Oct 2026: a fetched menu PDF (6 in 30 days) or a PDF the user attached
    never reached the verifier, so every fact from it was NO SOURCE."""

    def _labels(self, media: list[dict[str, Any]]) -> list[str]:
        return [b["text"] for b in media if b.get("type") == "text"]

    def test_a_fetched_pdf_reaches_the_verifier_as_unnumbered(
        self, fake_verifier: MagicMock
    ) -> None:
        check_grounding(
            "Polévka stojí 89 Kč.", [HumanMessage(content="menu?"), *_fetched_pdf_turn()]
        )

        media = fake_verifier.call_args.kwargs["images"]
        assert media[-1] == _PDF
        assert "UNNUMBERED" in self._labels(media)[-1]

    def test_a_users_pdf_is_known(self, fake_verifier: MagicMock) -> None:
        user = HumanMessage(content=[{"type": "text", "text": "tady je ceník"}, _PDF])

        check_grounding(_ANSWER, [user, *_WEB_TURN])

        media = fake_verifier.call_args.kwargs["images"]
        assert media[-1] == _PDF and "KNOWN" in self._labels(media)[0]
        assert "attached 1 file" in fake_verifier.call_args.args[2]

    def test_files_of_earlier_turns_are_not_sent(self, fake_verifier: MagicMock) -> None:
        messages = [
            HumanMessage(content="menu?"),
            *_fetched_pdf_turn(),
            AIMessage(content="Polévka 89 Kč."),
            HumanMessage(content="a v neděli?"),
            *_WEB_TURN,
        ]

        check_grounding(_ANSWER, messages)

        assert not fake_verifier.call_args.kwargs.get("images")


class TestGuidanceIsNotTheUser:
    """In cached mode the graph's round nudges and retries are HumanMessages
    ("[SYSTEM GUIDANCE] ..."): KNOWN quoted the nudge as the user's message
    and lost the user's images and the turn's earlier tool results."""

    def _messages(self) -> list[Any]:
        return [
            HumanMessage(content=[{"type": "text", "text": "kolik stojí brompton"}, _IMAGE]),
            AIMessage(content="", tool_calls=[{"name": "google_calendar", "args": {}, "id": "c1"}]),
            ToolMessage(content="Schůzka v 15:00", tool_call_id="c1", name="google_calendar"),
            HumanMessage(
                content="[SYSTEM GUIDANCE]\nYou have used 4 tool rounds.\n[/SYSTEM GUIDANCE]"
            ),
            *_WEB_TURN,
        ]

    def test_known_facts_skip_guidance(self) -> None:
        known = grounding_check.known_facts(self._messages())

        assert "The user wrote: kolik stojí brompton" in known
        assert "SYSTEM GUIDANCE" not in known
        assert "Schůzka v 15:00" in known
        assert "attached 1 file" in known

    def test_the_users_files_survive_guidance(self) -> None:
        assert grounding_check.user_files(self._messages()) == [_IMAGE]


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

    def test_prompt_never_lists_history_or_background_knowledge(self) -> None:
        # "Zajímavosti o Radobýlu" (Oct 3 2026): Mácha's death, a cross from
        # 1658 and a WWII factory were underlined as unsourced - background
        # knowledge, not the stale shop/price data the check exists for
        from src.agent.prompt_texts.grounding import GROUNDING_CHECK_PROMPT

        never = GROUNDING_CHECK_PROMPT[GROUNDING_CHECK_PROMPT.index("NEVER list:") :]
        assert "history" in never
        assert "upcoming or scheduled" in GROUNDING_CHECK_PROMPT

    def test_default_quote_cap_drops_sentences(self) -> None:
        assert Config.GROUNDING_CHECK_MAX_QUOTE_CHARS == 60


class TestCheckGroundingPages:
    """Deep research checks its report against merged pages with its own limits."""

    def test_limits_are_the_callers(self, fake_verifier: MagicMock) -> None:
        from src.agent.grounding_check import check_grounding_pages

        fake_verifier.return_value = (
            GroundingVerdict(
                unsupported=[
                    ClaimVerdict(quote="VeloRama", verdict="not_found"),
                    ClaimVerdict(quote="29 990 Kč", verdict="not_found"),
                ]
            ),
            _USAGE,
        )
        pages = [SourcePage("A", "https://a.cz", "x" * 1000)]

        outcome = check_grounding_pages(
            _ANSWER, pages, "", known="", max_source_chars=200, max_claims=1
        )

        assert len(fake_verifier.call_args.args[1]) < 300
        assert len(outcome.annotations) == 1
        # Without a caller timeout the chat turn's applies
        assert (
            fake_verifier.call_args.kwargs["timeout_seconds"]
            == Config.GROUNDING_CHECK_TIMEOUT_SECONDS
        )
        assert outcome.summary == {"checked": True, "source_count": 1}


def test_a_hedged_price_is_still_a_claim() -> None:
    """ "~25,000 CZK" or "Approx. price" opted every price out of the check
    (honesty probe, Oct 4 2026); only an explicit unverified label exempts."""
    from src.agent.prompt_texts.grounding import GROUNDING_CHECK_PROMPT

    assert "approximate or an estimate" not in GROUNDING_CHECK_PROMPT
    assert "~" in GROUNDING_CHECK_PROMPT and "cca" in GROUNDING_CHECK_PROMPT


class TestPriceNet:
    """Deterministic safety net: the verifier (Flash Lite) misses a price now
    and then (honesty probe, Oct 4 2026); every price not on a page read is
    marked even when the verifier skipped it."""

    _PAGES: ClassVar[list[SourcePage]] = [
        SourcePage("Shop", "https://shop.cz", "Brompton C Line: 43 300 Kč. Doprava zdarma.")
    ]

    def _check(self, answer: str, claims: list[ClaimVerdict]) -> list[dict[str, Any]]:
        from src.agent.grounding_check import check_grounding_pages

        return check_grounding_pages(
            answer, self._PAGES, "", known="", max_source_chars=10_000, max_claims=20
        ).annotations

    def test_a_missed_price_is_marked(self, fake_verifier: MagicMock) -> None:
        answer = "C Line stojí 43 300 Kč. Ojeté kusy na Bazoši typicky 20,000–30,000 CZK."
        fake_verifier.return_value = (
            GroundingVerdict(
                supported=[
                    ClaimVerdict(
                        quote="43 300 Kč", verdict="supported", source=1, source_quote="43 300 Kč"
                    )
                ]
            ),
            _USAGE,
        )

        anns = self._check(answer, [])

        net = [a for a in anns if a["verdict"] == "not_found"]
        assert [a["quote"] for a in net] == ["20,000–30,000 CZK"]
        assert "not on the pages" in net[0]["reason"]

    def test_a_price_on_a_page_is_left_alone(self, fake_verifier: MagicMock) -> None:
        """Written differently from the page (43,300 vs 43 300) is still the page's price."""
        fake_verifier.return_value = (
            GroundingVerdict(
                unsupported=[ClaimVerdict(quote="Bazoš", verdict="not_found", reason="r")]
            ),
            _USAGE,
        )

        anns = self._check("Na Bazoši. C Line za 43,300 CZK.", [])

        assert [a["quote"] for a in anns] == ["Bazoš"]

    def test_a_price_the_verifier_listed_is_not_doubled(self, fake_verifier: MagicMock) -> None:
        fake_verifier.return_value = (
            GroundingVerdict(
                unsupported=[
                    ClaimVerdict(quote="P Line ~71 000 Kč", verdict="not_found", reason="r")
                ]
            ),
            _USAGE,
        )

        anns = self._check("P Line ~71 000 Kč.", [])

        assert [a["quote"] for a in anns] == ["P Line ~71 000 Kč"]

    def test_euro_prices_count(self, fake_verifier: MagicMock) -> None:
        fake_verifier.return_value = (
            GroundingVerdict(
                unsupported=[ClaimVerdict(quote="Bazoš", verdict="not_found", reason="r")]
            ),
            _USAGE,
        )

        anns = self._check("Na Bazoši, v EU za €1,100 – €1,400.", [])

        assert "€1,100 – €1,400" in [a["quote"] for a in anns]

    def test_no_net_when_the_verifier_found_nothing_to_check(
        self, fake_verifier: MagicMock
    ) -> None:
        """An empty verdict means history/background: a 1990 price is not a shop claim."""
        assert self._check("V roce 1990 stál rohlík 30 haléřů a pivo 2 Kčs, dnes 45 Kč.", []) == []

    def test_an_explicitly_unverified_price_is_left_alone(self, fake_verifier: MagicMock) -> None:
        fake_verifier.return_value = (
            GroundingVerdict(
                unsupported=[ClaimVerdict(quote="Bazoš", verdict="not_found", reason="r")]
            ),
            _USAGE,
        )

        anns = self._check("Na Bazoši. Cenu 25 000 Kč se nepodařilo ověřit.", [])

        assert [a["quote"] for a in anns] == ["Bazoš"]

    def _only_bazos(self, fake_verifier: MagicMock, answer: str, **kw: Any) -> list[str]:
        from src.agent.grounding_check import check_grounding_pages

        fake_verifier.return_value = (
            GroundingVerdict(
                unsupported=[ClaimVerdict(quote="Bazoš", verdict="not_found", reason="r")]
            ),
            _USAGE,
        )
        args: dict[str, Any] = {"known": "", "max_source_chars": 10_000, "max_claims": 20}
        pages = kw.pop("pages", self._PAGES)
        anns = check_grounding_pages(answer, pages, "", **{**args, **kw}).annotations
        return [a["quote"] for a in anns]

    def test_a_markup_price_with_decimals_is_the_page_price(self, fake_verifier: MagicMock) -> None:
        """Oct 2026 prod: the product-data line reads "price 6490.0 CZK"; its
        digits 64900 never matched "6 490 Kč"."""
        pages = [
            SourcePage(
                "Apple",
                "https://apple.com/cz",
                "Product data (page markup): AirPods Pro 3 - price 6490.0 CZK",
            )
        ]

        quotes = self._only_bazos(
            fake_verifier, "AirPods Pro 3 za 6 490 Kč. Na Bazoši.", pages=pages
        )

        assert quotes == ["Bazoš"]

    def test_a_price_from_known_facts_is_not_flagged(self, fake_verifier: MagicMock) -> None:
        quotes = self._only_bazos(
            fake_verifier,
            "Do rozpočtu 30 000 Kč se C Line vejde. Na Bazoši.",
            known="The user wrote: mám rozpočet 30 000 Kč",
        )

        assert quotes == ["Bazoš"]

    @pytest.mark.parametrize(
        "answer",
        [
            "C Line za 43 300 Kč (cca 1 730 €). Na Bazoši.",
            "C Line za 43 300 Kč (tj. zhruba 1 730 €). Na Bazoši.",
            "Kurz: ~490 bodů = 20 €. Na Bazoši.",
        ],
    )
    def test_a_conversion_of_an_amount_is_not_a_new_price(
        self, fake_verifier: MagicMock, answer: str
    ) -> None:
        """Oct 2026 prod: about a third of the net's 35 price flags were the
        model's own conversions or per-unit splits of a nearby amount."""
        assert self._only_bazos(fake_verifier, answer) == ["Bazoš"]

    def test_the_amount_a_conversion_follows_is_still_checked(
        self, fake_verifier: MagicMock
    ) -> None:
        quotes = self._only_bazos(
            fake_verifier, "Apartmán 800–900 EUR za 4 noci (cca 200–225 EUR za noc). Na Bazoši."
        )

        assert quotes == ["800–900 EUR", "Bazoš"]

    def test_a_zero_price_is_not_a_claim(self, fake_verifier: MagicMock) -> None:
        assert self._only_bazos(fake_verifier, "Náklad na pokus: 0 Kč. Na Bazoši.") == ["Bazoš"]


class TestShopNet:
    """Linked or named sites the turn never read are marked (honesty probe:
    Cyklobazar, VeloRama, Citybikes left unmarked by the verifier)."""

    _PAGES = [  # noqa: RUF012 - a test replaces it per instance
        SourcePage(
            "Cyklospeciality",
            "https://www.cyklospeciality.cz/brompton",
            "Cyklospeciality prodává Brompton C Line za 43 300 Kč",
        )
    ]

    def _check(
        self,
        answer: str,
        fake_verifier: MagicMock,
        claims: list[ClaimVerdict] | None = None,
        uncited: str = "",
        known: str = "",
    ) -> list[dict[str, Any]]:
        from src.agent.grounding_check import check_grounding_pages

        listed = claims or [
            ClaimVerdict(
                quote="Cyklospeciality",
                verdict="supported",
                source=1,
                source_quote="Cyklospeciality",
            )
        ]
        fake_verifier.return_value = (GroundingVerdict(supported=listed), _USAGE)
        return check_grounding_pages(
            answer, self._PAGES, uncited, known=known, max_source_chars=10_000, max_claims=20
        ).annotations

    @pytest.mark.parametrize(
        ("answer", "uncited", "known"),
        [
            # Oct 2026 prod: the domain a read page was about (a domain auction)
            ("U Cyklospeciality. Doménu aicom.com prodali.", "", ""),
            # a site the user named in their message
            (
                "U Cyklospeciality, viz cesko.cz.",
                "",
                "The user wrote: kolik kandiduje cesko(cesko.cz)",
            ),
            # a site from a search snippet the model read
            ("U Cyklospeciality, nebo booking.com.", "Booking.com: Hotel Alfa from 120 €", ""),
        ],
    )
    def test_a_site_the_turn_already_mentions_is_left_alone(
        self, fake_verifier: MagicMock, answer: str, uncited: str, known: str
    ) -> None:
        self._PAGES = [
            SourcePage(
                "Cyklospeciality",
                "https://www.cyklospeciality.cz/brompton",
                "Cyklospeciality. aicom.com expired closed at $51,000.",
            )
        ]

        anns = self._check(answer, fake_verifier, uncited=uncited, known=known)

        assert [a["verdict"] for a in anns] == ["supported"]

    def test_an_unread_linked_shop_is_marked(self, fake_verifier: MagicMock) -> None:
        answer = "Prodává [Cyklospeciality](https://cyklospeciality.cz) a ojeté [Cyklobazar.cz](https://www.cyklobazar.cz/brompton)."

        anns = self._check(answer, fake_verifier)

        net = [(a["quote"], a["reason"]) for a in anns if a["verdict"] == "not_found"]
        assert net == [("Cyklobazar.cz", "This site is not among the pages read this turn.")]

    def test_a_bare_domain_counts(self, fake_verifier: MagicMock) -> None:
        anns = self._check("U Cyklospeciality, nebo na bazos.cz.", fake_verifier)

        assert ("not_found", "bazos.cz") in [(a["verdict"], a["quote"]) for a in anns]

    def test_a_read_site_on_another_path_is_left_alone(self, fake_verifier: MagicMock) -> None:
        anns = self._check(
            "U [Cyklospeciality](https://cyklospeciality.cz/kontakt).", fake_verifier
        )

        assert [a["verdict"] for a in anns] == ["supported"]

    def test_an_unverified_site_is_left_alone(self, fake_verifier: MagicMock) -> None:
        anns = self._check(
            "U Cyklospeciality. Citybikes.cz (neověřeno) je další možnost.", fake_verifier
        )

        assert "Citybikes.cz" not in [a["quote"] for a in anns]


class TestRecentNewsScope:
    """Oct 2026: answers about a September keynote and a council reshuffle got
    no verdicts at all - "past events" were out of scope. Recent news facts
    (last 12 months) are claims now, judged against TODAY."""

    def test_prompt_is_dated_and_covers_recent_news(self) -> None:
        from datetime import date

        from src.agent import grounding_check

        captured: list[str] = []
        structured = MagicMock()
        structured.invoke.side_effect = lambda prompt: captured.append(prompt)
        model = MagicMock()
        model.with_structured_output.return_value = structured
        with (
            patch.object(gemini_clients, "ChatGoogleGenerativeAI", return_value=model),
            patch.object(grounding_check, "_today", return_value=date(2026, 10, 10)),
        ):
            grounding_check._run_verifier("answer", "sources", "known")

        assert "TODAY: 2026-10-10" in captured[0]
        assert "RECENT NEWS" in captured[0]

    def test_present_tense_claims_are_marked_for_the_age_check(self) -> None:
        # Oct 2026: an Oct 2025 article "supported" a politician's party after
        # he had left it; the verifier marks such claims and the server judges
        # the article's age (TestStalePresentTense)
        from src.agent.prompt_texts.grounding import GROUNDING_CHECK_PROMPT

        assert "about_present=true" in GROUNDING_CHECK_PROMPT


class TestEarlierVerifiedClaims:
    """Facts sourced in an earlier turn are not 'unverified' when restated
    (Oct 2026: a follow-up flagged red what the previous turns had verified)."""

    _HISTORY: ClassVar[list[dict[str, Any]]] = [
        {"role": "user", "content": "Kdo vyhrál?", "metadata": {}},
        {
            "role": "assistant",
            "content": "Grolich vyhrál v 1. kole.",
            "metadata": {
                "verified_claims": [
                    {
                        "quote": "vyhrál v 1. kole",
                        "source_quote": "Grolich se stal už v prvním kole senátorem",
                        "title": "ČT24",
                        "url": "https://ct24.cz/grolich",
                    }
                ]
            },
        },
    ]

    def test_the_verifier_sees_earlier_evidence(self, fake_verifier: MagicMock) -> None:
        check_grounding(_ANSWER, _WEB_TURN, history=self._HISTORY)

        sources = fake_verifier.call_args.args[1]
        assert "Grolich se stal už v prvním kole senátorem" in sources
        assert "https://ct24.cz/grolich" in sources
        # Context, not a numbered page: the reply cannot cite it
        assert sources.index("UNNUMBERED") < sources.index("prvním kole senátorem")

    def test_no_history_no_earlier_block(self, fake_verifier: MagicMock) -> None:
        check_grounding(_ANSWER, _WEB_TURN)

        assert "earlier in this conversation" not in fake_verifier.call_args.args[1]


def test_an_old_article_cannot_back_a_present_tense_claim(
    fake_verifier: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import date

    monkeypatch.setattr(grounding_check, "_today", lambda: date(2026, 10, 12))
    turn = _research_turn("Published: 2025-10-05\n\nV ODS jsou lidé jako třeba pan Kuba.")
    fake_verifier.return_value = (
        GroundingVerdict(
            supported=[
                ClaimVerdict(
                    quote="Martin Kuba (ODS)",
                    verdict="supported",
                    source=1,
                    source_quote="V ODS jsou lidé jako třeba pan Kuba",
                    about_present=True,
                )
            ]
        ),
        _USAGE,
    )

    outcome = check_grounding("Martin Kuba (ODS) vede jižní Čechy.", turn)

    assert outcome.annotations[0]["verdict"] == "partial"
