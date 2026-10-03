"""Tests for the eval harness (case loading + judge parsing + checks).

Only the pure pieces are tested here - actually running evals hits the live
Gemini API and happens via `make eval`, never in CI.
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from evals.run import (
    EvalCase,
    case_timeout,
    deterministic_failures,
    in_case_order,
    load_cases,
    parse_judge_response,
    run_deep_research_turn,
    run_with_timeout,
    select_cases,
    turn_cost,
    write_results,
)


def _write_case(directory: Path, name: str, body: str) -> None:
    (directory / name).write_text(body)


class TestLoadCases:
    def test_loads_valid_case(self, tmp_path: Path) -> None:
        _write_case(
            tmp_path,
            "web_lookup.yaml",
            """
id: web_lookup
description: Current-fact question
user: What is the tallest building in the world right now?
expect:
  rubric: Answer names a building and cites a source.
  required_tools: [research, web_search]
""",
        )

        cases = load_cases(tmp_path)

        assert len(cases) == 1
        case = cases[0]
        assert case.id == "web_lookup"
        assert case.required_tools == ["research", "web_search"]
        assert case.forbidden_tools == []
        assert case.requires == []

    def test_rubric_date_placeholders_resolved(self, tmp_path: Path) -> None:
        _write_case(
            tmp_path,
            "dated.yaml",
            "id: dated\nuser: hi\nexpect:\n"
            "  rubric: Today is {today_weekday} {today}; in 10 days is {in_10_days_weekday}.\n",
        )

        rubric = load_cases(tmp_path)[0].rubric

        today = date.today()
        later = today + timedelta(days=10)
        assert rubric == (f"Today is {today:%A} {today.isoformat()}; in 10 days is {later:%A}.")

    def test_missing_rubric_rejected(self, tmp_path: Path) -> None:
        _write_case(tmp_path, "bad.yaml", "id: bad\nuser: hi\nexpect: {}\n")

        with pytest.raises(ValueError, match="rubric"):
            load_cases(tmp_path)


class TestParseJudgeResponse:
    def test_plain_json(self) -> None:
        score, passed, reasoning = parse_judge_response(
            '{"score": 4, "pass": true, "reasoning": "solid"}'
        )
        assert (score, passed, reasoning) == (4, True, "solid")

    def test_fenced_json(self) -> None:
        text = '```json\n{"score": 2, "pass": false, "reasoning": "missed citation"}\n```'
        score, passed, reasoning = parse_judge_response(text)
        assert (score, passed) == (2, False)

    def test_garbage_returns_failure(self) -> None:
        score, passed, reasoning = parse_judge_response("not json at all")
        assert passed is False
        assert score == 0


class TestDeterministicFailures:
    def _case(self, **expect: object) -> EvalCase:
        return EvalCase(
            id="c",
            description="",
            user="q",
            requires=[],
            rubric="r",
            required_tools=expect.get("required_tools", []),  # type: ignore[arg-type]
            forbidden_tools=expect.get("forbidden_tools", []),  # type: ignore[arg-type]
            max_tool_rounds=expect.get("max_tool_rounds", 0),  # type: ignore[arg-type]
            required_skill=expect.get("required_skill"),  # type: ignore[arg-type]
        )

    def test_required_tools_any_of(self) -> None:
        case = self._case(required_tools=["research", "web_search"])
        assert deterministic_failures(case, {"web_search"}, tool_rounds=1) == []
        assert deterministic_failures(case, {"fetch_url"}, tool_rounds=1)

    def test_forbidden_tools(self) -> None:
        case = self._case(forbidden_tools=["web_search"])
        assert deterministic_failures(case, {"web_search"}, tool_rounds=1)
        assert deterministic_failures(case, set(), tool_rounds=0) == []

    def test_required_skill_must_be_the_one_loaded(self) -> None:
        case = self._case(required_skill="office-documents")
        assert (
            deterministic_failures(
                case, {"load_skill"}, tool_rounds=1, skills_loaded={"office-documents"}
            )
            == []
        )
        assert deterministic_failures(
            case, {"load_skill"}, tool_rounds=1, skills_loaded={"pdf-documents"}
        )
        assert deterministic_failures(case, set(), tool_rounds=0)

    def test_skills_loaded_are_read_from_tool_call_args(self) -> None:
        from langchain_core.messages import AIMessage

        from evals.run import skills_loaded_in

        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "load_skill", "args": {"name": "office-documents"}, "id": "1"},
                    {"name": "execute_code", "args": {"code": "x"}, "id": "2"},
                ],
            )
        ]
        assert skills_loaded_in(messages) == {"office-documents"}

    def test_max_tool_rounds(self) -> None:
        case = self._case(max_tool_rounds=2)
        assert deterministic_failures(case, set(), tool_rounds=3)
        assert deterministic_failures(case, set(), tool_rounds=2) == []


class TestHistorySupport:
    def test_case_with_history_parses(self, tmp_path: Path) -> None:
        _write_case(
            tmp_path,
            "followup.yaml",
            """
id: followup
description: Follow-up question needing prior context
history:
  - role: user
    content: Plan me a weekend hike near Brno.
  - role: assistant
    content: "Suggested: Moravian Karst trail, 12 km, Saturday."
user: A co kdyz bude prset?
expect:
  rubric: Answer adapts the previously suggested plan to rain.
""",
        )

        cases = load_cases(tmp_path)

        assert cases[0].history == [
            {"role": "user", "content": "Plan me a weekend hike near Brno."},
            {"role": "assistant", "content": "Suggested: Moravian Karst trail, 12 km, Saturday."},
        ]

    def test_history_metadata_and_compaction_flag_parse(self, tmp_path: Path) -> None:
        _write_case(
            tmp_path,
            "recall.yaml",
            """
id: recall
description: Tool output recall
compact_history: true
history:
  - role: user
    content: hi
  - role: assistant
    content: done
    metadata:
      tool_outputs: 'garmin_connect({}) -> {"hrv":62}'
user: what was it?
expect:
  rubric: says 62
""",
        )
        case = load_cases(tmp_path)[0]
        assert case.compact_history is True
        assert case.history[1]["metadata"] == {"tool_outputs": 'garmin_connect({}) -> {"hrv":62}'}
        assert "metadata" not in case.history[0]

    def test_history_defaults_empty(self, tmp_path: Path) -> None:
        _write_case(tmp_path, "plain.yaml", "id: p\nuser: hi\nexpect: {rubric: r}\n")
        assert load_cases(tmp_path)[0].history == []


class TestSportsMode:
    def test_sports_case_parses(self, tmp_path: Path) -> None:
        _write_case(
            tmp_path,
            "sports.yaml",
            """
id: sports_case
mode: sports
program_kv:
  "cycling:routine": "po/st/pa 60min"
user: Odjeto.
expect:
  rubric: Coach feedback.
""",
        )

        case = load_cases(tmp_path)[0]

        assert case.mode == "sports"
        assert case.program_kv == {"cycling:routine": "po/st/pa 60min"}

    def test_mode_defaults_chat(self, tmp_path: Path) -> None:
        _write_case(tmp_path, "plain.yaml", "id: p\nuser: hi\nexpect: {rubric: r}\n")
        assert load_cases(tmp_path)[0].mode == "chat"


class TestFixtureAndSeedFields:
    def test_files_memories_and_seed_conversation_parse(self, tmp_path: Path) -> None:
        _write_case(
            tmp_path,
            "rich.yaml",
            """
id: rich
user: co je na obrazku?
files: [fixtures/opening_hours_sign.png]
memories:
  - content: "Alergie na penicilin"
    category: fact
seed_conversation:
  title: "Dárek pro babičku"
  messages:
    - role: user
      content: "Co koupit babičce?"
    - role: assistant
      content: "Navrhuji sedací polštář a kurz keramiky."
expect:
  rubric: r
""",
        )

        case = load_cases(tmp_path)[0]

        assert case.files == ["fixtures/opening_hours_sign.png"]
        assert case.memories == [{"content": "Alergie na penicilin", "category": "fact"}]
        assert case.seed_conversation["title"] == "Dárek pro babičku"
        assert len(case.seed_conversation["messages"]) == 2

    def test_rich_fields_default_empty(self, tmp_path: Path) -> None:
        _write_case(tmp_path, "plain.yaml", "id: p\nuser: hi\nexpect: {rubric: r}\n")
        case = load_cases(tmp_path)[0]
        assert case.files == []
        assert case.memories == []
        assert case.seed_conversation == {}


class TestDeepResearchCases:
    """A deep_research case runs the real pipeline with the case's plan."""

    def test_plan_parses(self, tmp_path: Path) -> None:
        _write_case(
            tmp_path,
            "dr.yaml",
            "id: dr\nuser: q\ndeep_research:\n  question: Q\n  context: Praha\n"
            "  sub_questions: [a, b]\nexpect: {rubric: r}\n",
        )
        case = load_cases(tmp_path)[0]
        assert case.deep_research == {
            "question": "Q",
            "context": "Praha",
            "sub_questions": ["a", "b"],
        }

    def test_plain_cases_have_no_plan(self, tmp_path: Path) -> None:
        _write_case(tmp_path, "plain.yaml", "id: p\nuser: hi\nexpect: {rubric: r}\n")
        assert load_cases(tmp_path)[0].deep_research == {}

    def test_turn_runs_the_pipeline_and_returns_its_final(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.agent.deep_research import pipeline

        seen = {}

        def fake_run(plan, recent_turns, request_id, finish_requested=lambda: False):  # type: ignore[no-untyped-def]
            seen["plan"] = plan
            yield {"type": "research_plan", "items": plan.sub_questions}
            yield {
                "type": "final",
                "content": "report",
                "result_messages": [],
                "tool_results": [],
                "usage_info": {"answer_model": "pro"},
            }

        monkeypatch.setattr(pipeline, "run_deep_research", fake_run)
        response, tool_results, usage, messages = run_deep_research_turn(
            {"question": "Q", "context": "Praha", "sub_questions": ["a", "b"]}, "req-1"
        )
        assert (response, tool_results, usage, messages) == (
            "report",
            [],
            {"answer_model": "pro"},
            [],
        )
        assert seen["plan"].sub_questions == ["a", "b"]
        assert seen["plan"].context == "Praha"
        assert seen["plan"].estimate["minutes"] > 0

    def test_a_run_gets_the_deep_research_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.config import Config

        monkeypatch.setattr(Config, "EVAL_CASE_TIMEOUT_SECONDS", 300.0)
        monkeypatch.setattr(Config, "DEEP_RESEARCH_RUN_TIMEOUT_SECONDS", 900)
        plain = EvalCase(id="p", description="", user="u")
        research = EvalCase(
            id="r", description="", user="u", deep_research={"sub_questions": ["a"]}
        )
        assert (case_timeout(plain), case_timeout(research)) == (300.0, 900)

    def test_cost_prices_the_writer_and_the_subagents(self) -> None:
        usage = {
            "input_tokens": 1000,
            "output_tokens": 1000,
            "answer_model": "gemini-3.1-pro-preview",
        }
        with_research = {
            **usage,
            "deep_research_usage": [
                {"model": "gemini-3-flash-preview", "input_tokens": 100_000, "output_tokens": 1000}
            ],
        }
        flash_priced = turn_cost("gemini-3-flash-preview", {**usage, "answer_model": None}, [])
        writer_priced = turn_cost("gemini-3-flash-preview", usage, [])
        assert writer_priced > flash_priced
        assert turn_cost("gemini-3-flash-preview", with_research, []) > writer_priced


class TestRunWithTimeout:
    """A case that never returns must not hang the whole suite.

    The agent path evals use (ChatAgent directly) has no client timeout -
    CHAT_TIMEOUT is enforced at the route layer - so a stalled TLS read blocks
    forever. Observed Sep 15 2026: a run sat in _ssl__SSLSocket_read for 5h38m
    and forfeited 27 completed cases.
    """

    def test_returns_the_value_when_the_case_finishes(self) -> None:
        assert run_with_timeout(lambda: {"id": "x", "pass": True}, timeout_s=5) == {
            "id": "x",
            "pass": True,
        }

    def test_raises_timeout_when_the_case_hangs(self) -> None:
        import threading

        never = threading.Event()  # never set; mimics a blocked socket read
        with pytest.raises(TimeoutError):
            run_with_timeout(lambda: never.wait(), timeout_s=0.2)

    def test_propagates_the_cases_own_exception(self) -> None:
        def boom() -> None:
            raise RuntimeError("case blew up")

        with pytest.raises(RuntimeError, match="case blew up"):
            run_with_timeout(boom, timeout_s=5)


class TestIncrementalResults:
    """Results are flushed after every case, so a hang or Ctrl-C keeps the
    cases already paid for instead of forfeiting the whole run's spend."""

    def test_writes_partial_results_after_each_case(self, tmp_path: Path) -> None:
        out = tmp_path / "run.json"
        write_results(out, [{"id": "a", "pass": True}])
        first = json.loads(out.read_text())
        assert [r["id"] for r in first["results"]] == ["a"]

        write_results(out, [{"id": "a", "pass": True}, {"id": "b", "pass": False}])
        second = json.loads(out.read_text())
        assert [r["id"] for r in second["results"]] == ["a", "b"]

    def test_partial_file_carries_cost_so_far(self, tmp_path: Path) -> None:
        out = tmp_path / "run.json"
        write_results(out, [{"id": "a", "pass": True, "cost_usd": 0.03}])
        assert json.loads(out.read_text())["cost"]["total_usd"] == 0.03

    def test_a_timed_out_case_is_unpriced_not_free(self, tmp_path: Path) -> None:
        """An abandoned case spent real tokens the harness never saw."""
        out = tmp_path / "run.json"
        write_results(
            out,
            [
                {"id": "a", "pass": True, "cost_usd": 0.03},
                {"id": "b", "pass": False, "error": "case exceeded 900s", "timed_out": True},
            ],
        )
        cost = json.loads(out.read_text())["cost"]
        assert cost["cases_priced"] == 1
        assert cost["unpriced_cases"] == ["b"]


def _cases(*ids: str) -> list[EvalCase]:
    return [EvalCase(id=i, description="", user="hi", rubric="r") for i in ids]


class TestSelectCases:
    """--only takes several ids or globs, so reruns share one process start."""

    def test_no_patterns_keeps_every_case(self) -> None:
        cases = _cases("a", "b")
        assert select_cases(cases, []) == cases

    def test_several_ids_and_globs_keep_case_order(self) -> None:
        cases = _cases("code_exec", "skill_pdf", "skill_trip", "web_search")
        picked = select_cases(cases, ["web_search", "skill_*"])
        assert [c.id for c in picked] == ["skill_pdf", "skill_trip", "web_search"]

    def test_comma_separated_patterns(self) -> None:
        picked = select_cases(_cases("a", "b", "c"), ["a,c"])
        assert [c.id for c in picked] == ["a", "c"]

    def test_a_pattern_matching_nothing_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="typo"):
            select_cases(_cases("a"), ["a", "typo"])


class TestInCaseOrder:
    """Workers finish out of order; the report and results file must not."""

    def test_finished_results_follow_case_order(self) -> None:
        done = {"c": {"id": "c"}, "a": {"id": "a"}}
        assert [r["id"] for r in in_case_order(_cases("a", "b", "c"), done)] == ["a", "c"]


class TestEvalSearchIsolation:
    """Evals must never spend the metered search quota: they load the real
    .env (same keys as prod) but count usage in a throwaway DB, so prod's
    quota counters never saw eval searches (Oct 2026)."""

    def test_metered_search_keys_are_blanked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import dotenv

        from evals.run import EVAL_BLANKED_SEARCH_KEYS, isolate_environment

        monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: True)
        monkeypatch.setenv("DATABASE_PATH", "unused")
        monkeypatch.setenv("EMBEDDINGS_ENABLED", "true")
        for key in EVAL_BLANKED_SEARCH_KEYS:
            monkeypatch.setenv(key, "real-key")

        isolate_environment()

        assert all(os.environ[key] == "" for key in EVAL_BLANKED_SEARCH_KEYS)

    def test_every_metered_provider_is_covered(self) -> None:
        from evals.run import EVAL_BLANKED_SEARCH_KEYS
        from src.utils import search_provider

        metered = [p for p in search_provider._PROVIDERS if p.monthly_quota() is not None]
        assert len(EVAL_BLANKED_SEARCH_KEYS) == len(metered)


def test_judge_sees_problem_claims_marked_in_place() -> None:
    # The UI underlines the claim where it stands; an end-of-answer list was
    # measured not to work (the reader, and the judge, take the text as fact)
    from evals.run import annotate_for_judge

    text = annotate_for_judge(
        "Buy at Bike Prague or VeloRama for 29 990 Kč.",
        {
            "annotations": [
                {"verdict": "supported", "quote": "Bike Prague", "source": 1},
                {"verdict": "not_found", "quote": "VeloRama", "reason": "Not in sources."},
                {"verdict": "contradicted", "quote": "29 990 Kč", "reason": "Source: 32 990 Kč"},
            ]
        },
    )

    assert text == (
        "Buy at Bike Prague [source 1] or VeloRama [UNSOURCED: Not in sources.] "
        "for 29 990 Kč [CONTRADICTED BY SOURCE: Source: 32 990 Kč]."
    )


def test_judge_text_unchanged_without_annotations() -> None:
    from evals.run import annotate_for_judge

    assert annotate_for_judge("Plain answer.", None) == "Plain answer."
