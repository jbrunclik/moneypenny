"""Tests for the eval harness (case loading + judge parsing + checks).

The pure pieces, plus one case run with the agent and judge faked - actually
running evals hits the live Gemini API and happens via `make eval`, never in CI.
"""

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

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
from src.utils.clock import local_today


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

        today = local_today()
        later = today + timedelta(days=10)
        assert rubric == (f"Today is {today:%A} {today.isoformat()}; in 10 days is {later:%A}.")

    def test_relative_date_placeholders_resolved(self, tmp_path: Path) -> None:
        _write_case(
            tmp_path,
            "relative.yaml",
            "id: relative\nuser: hi\nexpect:\n"
            "  rubric: '{yesterday} {tomorrow} {3_days_ago} {in_2_days} {next_week}'\n",
        )

        rubric = load_cases(tmp_path)[0].rubric

        today = local_today()
        days = [today + timedelta(days=n) for n in (-1, 1, -3, 2)]
        assert rubric == " ".join(d.isoformat() for d in days) + " {next_week}"

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
        score, passed, _reasoning = parse_judge_response(text)
        assert (score, passed) == (2, False)

    def test_garbage_returns_failure(self) -> None:
        score, passed, _reasoning = parse_judge_response("not json at all")
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

    def test_forbidden_arg_patterns_check_the_named_tool_argument(self) -> None:
        case = self._case()
        case.forbidden_arg_patterns = {"create_artifact.html": [r"#[0-9a-fA-F]{3,8}\b"]}
        hex_call = {"name": "create_artifact", "args": {"html": "<p style='color:#fff'>x</p>"}}
        token_call = {
            "name": "create_artifact",
            "args": {"html": "<p style='color:var(--mp-text)'>x</p>"},
        }
        other_tool = {"name": "create_file", "args": {"html": "#fff"}}

        failures = deterministic_failures(case, set(), tool_rounds=1, tool_calls=[hex_call])
        assert failures and "create_artifact.html" in failures[0]
        assert deterministic_failures(case, set(), tool_rounds=1, tool_calls=[token_call]) == []
        assert deterministic_failures(case, set(), tool_rounds=1, tool_calls=[other_tool]) == []

    def test_required_arg_patterns_need_a_matching_call(self) -> None:
        case = self._case()
        case.required_arg_patterns = {"manage_memory.operations": [r"valid_until"]}
        dated = {"name": "manage_memory", "args": {"operations": [{"valid_until": "2026-11-21"}]}}
        undated = {"name": "manage_memory", "args": {"operations": [{"content": "x"}]}}

        assert deterministic_failures(case, set(), tool_rounds=1, tool_calls=[dated]) == []
        failures = deterministic_failures(case, set(), tool_rounds=1, tool_calls=[undated])
        assert failures and "manage_memory.operations" in failures[0]
        assert deterministic_failures(case, set(), tool_rounds=1, tool_calls=[])

    def test_required_action_missing_fails(self) -> None:
        case = self._case()
        case.required_actions = {"garmin": [r"^updated workout"]}
        failures = deterministic_failures(case, set(), tool_rounds=1, actions={"garmin": []})
        assert len(failures) == 1
        assert "garmin" in failures[0] and "^updated workout" in failures[0]

    def test_required_action_matched_passes(self) -> None:
        case = self._case()
        case.required_actions = {"garmin": [r"^updated workout"]}
        actions = {"garmin": ["updated workout 'Push A': Bench press weight 60->62.5 kg"]}
        assert deterministic_failures(case, set(), tool_rounds=1, actions=actions) == []

    def test_required_action_for_absent_fake_fails(self) -> None:
        case = self._case()
        case.required_actions = {"calendar": [r"^created event"]}
        failures = deterministic_failures(case, set(), tool_rounds=1, actions={})
        assert failures and "calendar" in failures[0]

    def test_required_actions_parse_from_yaml(self, tmp_path: Path) -> None:
        _write_case(
            tmp_path,
            "log.yaml",
            "id: log\nuser: u\nexpect:\n  rubric: r\n"
            "  required_actions:\n    todoist: ['^created task']\n",
        )
        [case] = load_cases(tmp_path)
        assert case.required_actions == {"todoist": ["^created task"]}

    def test_forbidden_arg_patterns_parse_from_yaml(self, tmp_path: Path) -> None:
        _write_case(
            tmp_path,
            "art.yaml",
            r"""
id: art
description: d
user: q
expect:
  rubric: r
  forbidden_arg_patterns:
    create_artifact.html: ['#[0-9a-f]{6}', 'width:\s*\d+px']
""",
        )
        [case] = load_cases(tmp_path)
        assert case.forbidden_arg_patterns == {
            "create_artifact.html": ["#[0-9a-f]{6}", r"width:\s*\d+px"]
        }

    def test_tool_calls_in_reads_names_and_args(self) -> None:
        from langchain_core.messages import AIMessage

        from evals.run import tool_calls_in

        messages = [
            AIMessage(
                content="",
                tool_calls=[{"name": "create_artifact", "args": {"html": "x"}, "id": "1"}],
            )
        ]
        assert tool_calls_in(messages) == [{"name": "create_artifact", "args": {"html": "x"}}]


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
            "answer_model": "gemini-4-carbon",
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
    CHAT_TIMEOUT_SECONDS is enforced at the route layer - so a stalled TLS read blocks
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

    def test_blobs_go_to_the_temp_dir_not_the_dev_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Eval attachments and generated files must not land in the repo's files.db."""
        import dotenv

        from evals.run import isolate_environment

        monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: True)
        monkeypatch.setenv("DATABASE_PATH", "unused")
        monkeypatch.setenv("BLOB_STORAGE_PATH", "files.db")

        isolate_environment()

        blobs = Path(os.environ["BLOB_STORAGE_PATH"])
        assert blobs.is_absolute()
        assert blobs.parent == Path(os.environ["DATABASE_PATH"]).parent

    def test_every_metered_provider_is_covered(self) -> None:
        from evals.run import EVAL_BLANKED_SEARCH_KEYS
        from src.services import search_provider

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


class TestArtifactSeeding:
    def test_artifacts_parse_and_ids_fill_the_history(self, tmp_path: Path) -> None:
        from evals.run import with_artifact_ids

        _write_case(
            tmp_path,
            "rev.yaml",
            """
id: rev
description: d
user: add 15 %
artifacts:
  - title: Tips
    html: "<p>10 %</p>"
history:
  - role: assistant
    content: Here is your calculator.
    metadata:
      artifacts: "{artifact_0} v1 'Tips'"
expect:
  rubric: r
""",
        )
        [case] = load_cases(tmp_path)
        assert case.artifacts == [{"title": "Tips", "html": "<p>10 %</p>"}]

        history = with_artifact_ids(case.history, ["abc123"])

        assert history[0]["metadata"]["artifacts"] == "abc123 v1 'Tips'"
        assert case.history[0]["metadata"]["artifacts"] == "{artifact_0} v1 'Tips'"


class TestRunCase:
    """One case end to end with the agent and the judge faked (no API calls)."""

    def test_seeds_runs_judges_and_cleans_up(
        self, monkeypatch: pytest.MonkeyPatch, test_database: Any, test_user: Any
    ) -> None:
        from langchain_core.messages import AIMessage, ToolMessage

        import evals.run as eval_run
        from src.agent import agent as agent_module

        calls: dict[str, Any] = {}

        class FakeAgent:
            def __init__(self, **kwargs: Any) -> None:
                calls["init"] = kwargs

            def chat_batch(self, **kwargs: Any) -> tuple[Any, ...]:
                calls["chat"] = kwargs
                from src.agent.round_cap import tool_round_cap

                calls["round_cap"] = tool_round_cap()
                calls["memories_during_turn"] = [
                    m.content for m in test_database.list_memories(test_user.id)
                ]
                messages = [
                    ToolMessage(name="web_search", content="x", tool_call_id="1"),
                    AIMessage(
                        content="",
                        tool_calls=[{"name": "set_conversation_title", "args": {}, "id": "2"}],
                    ),
                ]
                usage = {"tool_rounds": 1, "input_tokens": 100, "output_tokens": 20}
                return "The answer", [], usage, messages

        class FakeJudge:
            def __init__(self, **kwargs: Any) -> None:
                pass

            def invoke(self, messages: list[Any]) -> AIMessage:
                calls["judge_prompt"] = messages[0].content
                return AIMessage(
                    content='{"score": 4, "pass": true, "reasoning": "fine"}',
                    usage_metadata={"input_tokens": 50, "output_tokens": 10, "total_tokens": 60},
                )

        monkeypatch.setattr(agent_module, "ChatAgent", FakeAgent)
        monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", FakeJudge)

        case = EvalCase(
            id="c1",
            description="",
            user="What did I say?",
            rubric="Recalls the fact",
            mode="sports",
            program_kv={"ftp": "250"},
            round_cap=1,
            files=["fixtures/opening_hours_sign.png"],
            memories=[{"content": "Likes tea", "category": "preference"}],
            seed_conversation={
                "title": "Old chat",
                "messages": [{"role": "user", "content": "hi"}],
            },
            artifacts=[{"title": "Chart", "html": "<p>x</p>"}],
            history=[{"role": "user", "content": "see {artifact_0}"}],
        )
        result = eval_run._run_case(case, test_user, test_database)

        assert calls["round_cap"] == 1  # the case's cap applies to its turn only
        assert calls["init"]["standing"].kind == "sports"
        assert "250" in calls["init"]["standing"].data
        assert calls["chat"]["files"][0]["name"] == "opening_hours_sign.png"
        assert calls["chat"]["files"][0]["type"] == "image/png"
        assert "{artifact_0}" not in calls["chat"]["history"][0]["content"]
        assert calls["memories_during_turn"] == ["Likes tea"]
        assert "Recalls the fact" in calls["judge_prompt"]
        assert "set_conversation_title, web_search" in calls["judge_prompt"]
        titles = {
            c.title for c, _, _ in test_database.list_conversations_with_message_count(test_user.id)
        }
        assert "Old chat" in titles
        # A program case runs in the program's own chat (its tools resolve the program)
        [program_chat] = test_database.list_program_conversations("sports", test_user.id)
        assert program_chat.sports_program == "cycling"
        # Seeded memories don't leak into later cases
        assert test_database.list_memories(test_user.id) == []

        assert result["pass"] is True
        assert result["score"] == 4
        assert result["tool_rounds"] == 1
        assert result["tools_used"] == ["set_conversation_title", "web_search"]
        assert result["judge_input_tokens"] == 50
        assert result["cost_usd"] == pytest.approx(
            result["agent_cost_usd"] + result["judge_cost_usd"], abs=1e-6
        )
        assert result["agent_cost_usd"] > 0 and result["judge_cost_usd"] > 0
        assert result["deterministic_failures"] == []
        assert result["response_preview"] == "The answer"


class TestConversationFacts:
    """A case may seed the conversation's settled facts; the harness then runs
    it with conversation facts switched on (docs/features/conversation-facts.md)."""

    def test_facts_parse_and_default_to_off(self, tmp_path: Path) -> None:
        _write_case(
            tmp_path,
            "facts.yaml",
            """
id: f
conversation_facts:
  - {key: walls, text: All partitions are reinforced concrete}
user: hi
expect: {rubric: r}
""",
        )
        _write_case(tmp_path, "plain.yaml", "id: p\nuser: hi\nexpect: {rubric: r}\n")
        by_id = {c.id: c for c in load_cases(tmp_path)}
        assert by_id["f"].conversation_facts == [
            {"key": "walls", "text": "All partitions are reinforced concrete"}
        ]
        assert by_id["p"].conversation_facts is None

    def test_a_facts_case_reaches_the_turn_with_the_feature_on(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock, patch

        from evals import run
        from src.config import Config

        _write_case(
            tmp_path,
            "facts.yaml",
            "id: f\nconversation_facts: []\nuser: hi\nexpect: {rubric: r}\n",
        )
        [case] = load_cases(tmp_path)
        seen: dict[str, Any] = {}

        def fake_agent(**_kwargs: Any) -> MagicMock:
            seen["enabled"] = Config.CONVERSATION_FACTS_ENABLED
            agent = MagicMock()
            agent.chat_batch.return_value = ("ok", [], {}, [])
            seen["agent"] = agent
            return agent

        with patch("src.agent.agent.ChatAgent", side_effect=fake_agent):
            run._run_turn(case, MagicMock(id="u"), "c", "r", None, None)

        assert seen["enabled"] is True
        assert Config.CONVERSATION_FACTS_ENABLED is False  # restored after the case
        assert seen["agent"].chat_batch.call_args.kwargs["conversation_facts"] == []

    def test_the_run_wide_flag_gives_every_case_an_empty_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CONVERSATION_FACTS_ENABLED=true for a whole run measures what
        ordinary turns cost with the feature on (the rollout check)."""
        from unittest.mock import MagicMock, patch

        from evals import run
        from src.config import Config

        monkeypatch.setattr(Config, "CONVERSATION_FACTS_ENABLED", True)
        _write_case(tmp_path, "plain.yaml", "id: p\nuser: hi\nexpect: {rubric: r}\n")
        [case] = load_cases(tmp_path)
        agent = MagicMock()
        agent.chat_batch.return_value = ("ok", [], {}, [])

        with patch("src.agent.agent.ChatAgent", return_value=agent):
            run._run_turn(case, MagicMock(id="u"), "c", "r", None, None)

        assert agent.chat_batch.call_args.kwargs["conversation_facts"] == []


class TestHistoryFiles:
    """A file on an earlier turn (the floor-plan situation): stored like an
    upload, and listed in the history metadata the way production lists it."""

    def test_history_files_parse(self, tmp_path: Path) -> None:
        _write_case(
            tmp_path,
            "plan.yaml",
            """
id: plan
description: file on an earlier turn
history:
  - role: user
    content: Here is our flat
    files: [fixtures/floor_plan.pdf]
  - role: assistant
    content: Got it.
user: total area?
expect:
  rubric: says the area
""",
        )
        case = load_cases(tmp_path)[0]
        assert case.history[0]["files"] == ["fixtures/floor_plan.pdf"]
        assert "files" not in case.history[1]

    def test_history_files_are_stored_and_listed(self, test_database, test_user) -> None:
        from evals.run import _history_with_files

        conv = test_database.create_conversation(test_user.id, "Flat")
        history = [
            {"role": "user", "content": "Here is our flat", "files": ["fixtures/floor_plan.pdf"]},
            {"role": "assistant", "content": "Got it."},
        ]

        built = _history_with_files(history, test_database, conv.id)

        listed = built[0]["metadata"]["files"][0]
        assert listed["name"] == "floor_plan.pdf"
        assert listed["file_index"] == 0
        stored = test_database.get_message_by_id(listed["message_id"])
        assert stored is not None and stored.conversation_id == conv.id
        assert built[1]["role"] == "assistant"

    def test_current_turn_files_are_saved_with_their_ids(self, test_database, test_user) -> None:
        """Like production: the current message is saved with its uploads, and
        each upload carries its history id for execute_code(files=...)."""
        from evals.run import EvalCase, _saved_attachments

        conv = test_database.create_conversation(test_user.id, "Flat")
        case = EvalCase(
            id="c", description="", user="Draw it", rubric="r", files=["fixtures/floor_plan.pdf"]
        )

        payload = _saved_attachments(case, test_database, conv.id)

        message_id, _, index = payload[0]["history_file_id"].partition(":")
        stored = test_database.get_message_by_id(message_id)
        assert stored is not None and stored.conversation_id == conv.id and index == "0"
        assert payload[0]["name"] == "floor_plan.pdf"


def test_a_seeded_card_is_answered_before_the_turn(test_database: Any, test_user: Any) -> None:
    """The confirm case: the user's yes approves the seeded card first, as the
    chat route does, and the agent's text carries the outcome."""
    from evals.run import _seed_proposals, _turn_text
    from src.db.models import use_database

    [case] = [c for c in load_cases(Path("evals/cases")) if c.id == "schedule_reminder_confirm"]
    conv = test_database.create_conversation(test_user.id)
    with use_database(test_database):
        _seed_proposals(case, test_user, test_database, conv.id)
        text = _turn_text(case, conv.id)

    assert "The user approved" in text and "Reminder set" in text
    [item] = test_database.list_items(test_user.id)
    assert item.text == "Zavolat instalatérovi"


class TestRunLogAndTargets:
    """Nov 17 2026: results were gitignored (no history to compare against),
    chronic failures made every run read red, and there was no cheap subset
    to run on agent changes."""

    def test_smoke_and_known_failure_parse_from_yaml(self, tmp_path: Path) -> None:
        _write_case(
            tmp_path,
            "a.yaml",
            "id: a\nsmoke: true\nknown_failure: not batched yet\ndescription: d\nuser: q\n"
            "expect:\n  rubric: r\n",
        )
        _write_case(tmp_path, "b.yaml", "id: b\ndescription: d\nuser: q\nexpect:\n  rubric: r\n")
        a, b = load_cases(tmp_path)
        assert (a.smoke, a.known_failure) == (True, "not batched yet")
        assert (b.smoke, b.known_failure) == (False, None)

    def test_a_failing_known_target_is_not_a_failure(self) -> None:
        from evals.run import _status

        assert _status({"pass": False, "known_failure": "x"}) == "TARGET"
        assert _status({"pass": False}) == "FAIL"
        assert _status({"pass": True, "known_failure": "x"}) == "PASS"

    def test_history_line(self, tmp_path: Path) -> None:
        from evals.run import append_history, history_line

        results = [
            {"id": "a", "pass": True, "score": 5},
            {"id": "b", "pass": False, "score": 2, "known_failure": "x"},
            {"id": "c", "skipped": True},
        ]
        cost = {"agent_model": "m", "judge_model": "j", "total_usd": 0.123456}
        line = history_line(results, cost, "smoke", 90.0)

        assert line["passed"] == 1 and line["ran"] == 2
        assert line["known_failing"] == ["b"]
        assert line["cases"] == {"a": [True, 5, None], "b": [False, 2, None]}
        assert (line["selection"], line["cost_usd"], line["minutes"]) == ("smoke", 0.1235, 1.5)

        path = tmp_path / "history.jsonl"
        append_history(path, line)
        append_history(path, line)
        assert [json.loads(raw)["sha"] for raw in path.read_text().splitlines()] == [
            line["sha"]
        ] * 2


def test_a_fake_recorded_write_reaches_required_actions(
    monkeypatch: pytest.MonkeyPatch, test_database: Any, test_user: Any
) -> None:
    """The fakes' recorded actions feed both the judge and required_actions."""
    from langchain_core.messages import AIMessage

    import evals.run as eval_run
    from src.agent import agent as agent_module

    judged: list[str] = []

    class WritingAgent:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def chat_batch(self, **kwargs: Any) -> tuple[Any, ...]:
            from src.agent.tools import todoist_client

            todoist_client.todoist_api_request("POST", "/tasks", "fake", {"content": "Buy milk"})
            return "Done", [], {"tool_rounds": 1}, []

    class Judge:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def invoke(self, messages: list[Any]) -> AIMessage:
            judged.append(messages[0].content)
            return AIMessage(content='{"score": 5, "pass": true, "reasoning": "ok"}')

    monkeypatch.setattr(agent_module, "ChatAgent", WritingAgent)
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", Judge)

    def case(pattern: str) -> EvalCase:
        return EvalCase(
            id="w",
            description="",
            user="Add milk",
            rubric="r",
            integrations={"todoist": {"projects": [{"id": "p1", "name": "Inbox"}]}},
            required_actions={"todoist": [pattern]},
        )

    ok = eval_run._run_case(case("^created task 'Buy milk'"), test_user, test_database)
    assert ok["deterministic_failures"] == []
    assert "created task 'Buy milk'" in judged[0]
    missed = eval_run._run_case(case("^completed task"), test_user, test_database)
    assert missed["pass"] is False
    assert "todoist recorded no action" in missed["deterministic_failures"][0]


def test_web_spec_loads_canned_or_live(tmp_path: Path) -> None:
    _write_case(
        tmp_path,
        "a.yaml",
        "id: a\nuser: u\nweb: live\nexpect: {rubric: r}\n",
    )
    _write_case(
        tmp_path,
        "b.yaml",
        "id: b\nuser: u\nweb:\n  results: [{url: 'https://x.example', title: t, snippet: s}]\n"
        "expect: {rubric: r}\n",
    )
    _write_case(tmp_path, "c.yaml", "id: c\nuser: u\nexpect: {rubric: r}\n")
    a, b, c = load_cases(tmp_path)
    assert a.web == "live"
    assert isinstance(b.web, dict) and b.web["results"][0]["url"] == "https://x.example"
    assert c.web is None


def test_a_case_runs_on_canned_web_unless_live(
    monkeypatch: pytest.MonkeyPatch, test_database: Any, test_user: Any
) -> None:
    """The turn searches the case's canned results; the result says which web ran."""
    from langchain_core.messages import AIMessage

    import evals.run as eval_run
    from src.agent import agent as agent_module

    found: list[Any] = []

    class SearchingAgent:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def chat_batch(self, **kwargs: Any) -> tuple[Any, ...]:
            from src.services.search_provider import search_web

            found.append(search_web("q", 5))
            return "Done", [], {"tool_rounds": 1}, []

    class Judge:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def invoke(self, messages: list[Any]) -> AIMessage:
            return AIMessage(content='{"score": 5, "pass": true, "reasoning": "ok"}')

    monkeypatch.setattr(agent_module, "ChatAgent", SearchingAgent)
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", Judge)
    web = {"results": [{"url": "https://x.example", "title": "t", "snippet": "s"}]}
    case = EvalCase(id="w", description="", user="u", rubric="r", web=web)

    result = eval_run._run_case(case, test_user, test_database)
    assert found[0][0]["url"] == "https://x.example"
    assert result["web"] == "canned"


class TestModelAndGate:
    def test_chat_model_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from evals.run import chat_model
        from src.config import Config

        monkeypatch.delenv("EVAL_CHAT_MODEL", raising=False)
        assert chat_model() == Config.DEFAULT_MODEL
        monkeypatch.setenv("EVAL_CHAT_MODEL", "gemini-4-carbon")
        assert chat_model() == "gemini-4-carbon"

    def test_unpriced_model_is_rejected(self) -> None:
        from evals.run import check_model

        assert check_model("gemini-4-hydrogen") is None
        error = check_model("gemini-9-nope")
        assert error and "gemini-9-nope" in error and "gemini-4-hydrogen" in error

    def test_gate_verdict_and_model_recorded(
        self, monkeypatch: pytest.MonkeyPatch, test_database: Any, test_user: Any
    ) -> None:
        from langchain_core.messages import AIMessage

        import evals.run as eval_run
        from src.agent import agent as agent_module
        from src.agent import freshness

        init: dict[str, Any] = {}

        class GatedAgent:
            def __init__(self, **kwargs: Any) -> None:
                init.update(kwargs)

            def chat_batch(self, **kwargs: Any) -> tuple[Any, ...]:
                freshness.decide_freshness([], None)
                return "Done", [], {"tool_rounds": 0}, []

        class Judge:
            def __init__(self, **kwargs: Any) -> None:
                pass

            def invoke(self, messages: list[Any]) -> AIMessage:
                return AIMessage(content='{"score": 5, "pass": true, "reasoning": "ok"}')

        monkeypatch.setattr(
            freshness,
            "decide_freshness",
            lambda *a: freshness.FreshnessDecision(lookup=False, thinking="low"),
        )
        monkeypatch.setattr(agent_module, "ChatAgent", GatedAgent)
        monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", Judge)
        monkeypatch.setenv("EVAL_CHAT_MODEL", "gemini-4-carbon")

        case = EvalCase(id="g", description="", user="u", rubric="r")
        result = eval_run._run_case(case, test_user, test_database)
        assert init["model_name"] == "gemini-4-carbon"
        assert result["gate"] == {"thinking": "low", "lookup": False}
        assert result["model"] == "gemini-4-carbon"

    def test_no_gate_call_records_none(self) -> None:
        from evals.run import _gate_summary

        assert _gate_summary([]) is None


class TestHistoryLine:
    def _results(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "a",
                "pass": True,
                "score": 5,
                "web": "canned",
                "repeat": 0,
                "gate": {"thinking": "low", "lookup": False},
                "cost_usd": 0.02,
            },
            {
                "id": "b",
                "pass": False,
                "score": 2,
                "web": "live",
                "repeat": 0,
                "gate": {"thinking": "high", "lookup": True},
                "cost_usd": 0.08,
            },
            {
                "id": "a",
                "pass": False,
                "score": 3,
                "web": "canned",
                "repeat": 1,
                "gate": {"thinking": "low", "lookup": False},
                "cost_usd": 0.02,
            },
            {
                "id": "b",
                "pass": True,
                "score": 4,
                "web": "live",
                "repeat": 1,
                "gate": {"thinking": "high", "lookup": True},
                "cost_usd": 0.08,
            },
        ]

    def test_single_run_line(self) -> None:
        from evals.run import _cost_summary, history_line

        results = self._results()[:2]
        line = history_line(results, _cost_summary(results), "all", 60.0)
        assert line["repeat"] == 1
        assert line["web"] == {"canned": 1, "live": 1}
        assert line["gate_low"] == 1
        assert line["cases"]["a"] == [True, 5, "low"]
        assert "model" not in line  # agent_model says it

    def test_repeated_line_counts_passes_per_case(self) -> None:
        from evals.run import _cost_summary, history_line

        results = self._results()
        line = history_line(results, _cost_summary(results), "all", 60.0, repeat=2)
        assert line["repeat"] == 2
        assert line["passed"] == 2 and line["ran"] == 4
        assert line["cases"]["a"] == [1, 2, 4.0, "low"]
        assert line["web"] == {"canned": 1, "live": 1}

    def test_live_web_share_of_cost(self) -> None:
        from evals.run import _cost_summary

        cost = _cost_summary(self._results())
        assert cost["live_web_usd"] == pytest.approx(0.16)


def test_czech_weekday_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixture prose names days ("v úterý keramika") from the same relative
    dates as its calendar, so the two never disagree whatever day it runs."""
    from datetime import date

    import evals.run as eval_run

    monkeypatch.setattr(eval_run, "local_today", lambda: date(2026, 11, 18))  # a Wednesday
    assert eval_run._resolve_dates("{tomorrow_cs} a {in_3_days_cs}") == "čtvrtek a sobota"
    assert eval_run._resolve_dates("{today_weekday}") == "Wednesday"


def test_weekday_placeholders_land_on_that_weekday(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import date

    import evals.run as eval_run

    monkeypatch.setattr(eval_run, "local_today", lambda: date(2026, 11, 18))  # a Wednesday
    assert eval_run._resolve_dates("{tuesday}") == "2026-11-24"  # next one, not today's week
    assert eval_run._resolve_dates("{thursday}") == "2026-11-19"
    assert eval_run._resolve_dates("{wednesday}") == "2026-11-25"  # strictly after today
    assert eval_run._resolve_dates("{thursday_plus_7}") == "2026-11-26"
    assert eval_run._resolve_dates("{saturday_cs}") == "sobota"


def test_a_result_records_what_the_turn_did_on_the_canned_web(
    monkeypatch: pytest.MonkeyPatch, test_database: Any, test_user: Any
) -> None:
    from langchain_core.messages import AIMessage

    import evals.run as eval_run
    from src.agent import agent as agent_module

    class FetchingAgent:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def chat_batch(self, **kwargs: Any) -> tuple[Any, ...]:
            from src.agent.tools.web import fetch_page_text

            fetch_page_text("https://missing.example.org/page")
            return "Done", [], {"tool_rounds": 1}, []

    class Judge:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def invoke(self, messages: list[Any]) -> AIMessage:
            return AIMessage(content='{"score": 5, "pass": true, "reasoning": "ok"}')

    monkeypatch.setattr(agent_module, "ChatAgent", FetchingAgent)
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", Judge)
    result = eval_run._run_case(
        EvalCase(id="w", description="", user="u", rubric="r"), test_user, test_database
    )
    assert result["web_calls"] == {
        "searches": 0,
        "fetched": ["https://missing.example.org/page"],
        "missing": ["https://missing.example.org/page"],
    }


def test_judge_is_told_the_grounding_tags_are_the_harness_s() -> None:
    """The judge read the in-place grounding tags as markup the assistant
    leaked ("outputs raw '[UNSOURCED]' tags") and failed correct answers."""
    from evals.run import _JUDGE_INSTRUCTION

    prompt = _JUDGE_INSTRUCTION.format(
        rubric="r",
        user="u",
        response="a [UNSOURCED: x]",
        tools_called="none",
        cited_sources="none",
        integration_changes="none",
    )
    flat = " ".join(prompt.split())
    assert "inserted by the grading harness" in flat
    assert "not text the assistant wrote" in flat


def test_history_content_dates_resolve(tmp_path: Path) -> None:
    _write_case(
        tmp_path,
        "d.yaml",
        "id: d\nuser: u\nhistory:\n  - role: user\n"
        "    content: 'exam on {tomorrow}, table {artifact_0}'\nexpect: {rubric: r}\n",
    )
    [case] = load_cases(tmp_path)
    content = case.history[0]["content"]
    assert "{tomorrow}" not in content and "{artifact_0}" in content


def test_user_message_and_long_dates_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pasted notice in the user's message names its day: "Tuesday 12
    November" went stale (and wrong - it was a Thursday) a week after writing."""
    from datetime import date

    import evals.run as eval_run

    monkeypatch.setattr(eval_run, "local_today", lambda: date(2026, 11, 18))  # a Wednesday
    _write_case(
        tmp_path,
        "n.yaml",
        "id: n\nuser: 'Water off on {tuesday_long} 9:00-13:00'\nexpect: {rubric: 'on {tuesday_long}'}\n",
    )
    [case] = load_cases(tmp_path)
    assert case.user == "Water off on Tuesday 24 November 9:00-13:00"
    assert case.rubric == "on Tuesday 24 November"


class TestInfrastructure:
    """A throttled live search or a gap in a canned capture is not the agent."""

    def _tool(self, name: str, content: str) -> Any:
        from langchain_core.messages import ToolMessage

        return ToolMessage(name=name, content=content, tool_call_id="1")

    def test_search_outage_needs_every_search_to_fail(self) -> None:
        from evals.run import search_outage

        failed = self._tool(
            "web_search", '{"query": "q", "results": [], "error": "No results found."}'
        )
        research_failed = self._tool(
            "research",
            '{"error": "All searches failed (search providers unavailable). Try again"}',
        )
        worked = self._tool("web_search", '{"query": "q", "results": [{"url": "u"}]}')
        empty = self._tool("web_search", '{"query": "q", "results": [], "note": "No results"}')
        assert search_outage([failed, research_failed]) is True
        assert search_outage([failed, worked]) is False
        assert search_outage([empty]) is False  # found nothing is a real outcome
        assert search_outage([self._tool("todoist", "{}")]) is False

    def test_infra_status_and_log(self) -> None:
        from evals.run import _cost_summary, _status, history_line

        results = [
            {"id": "a", "pass": False, "score": 1, "infra": "live search failed", "web": "live"},
            {
                "id": "b",
                "pass": True,
                "score": 5,
                "web": "canned",
                "web_calls": {"searches": 1, "fetched": ["u"], "missing": ["u"]},
            },
        ]
        assert _status(results[0]) == "INFRA"
        line = history_line(results, _cost_summary(results), "all", 60.0)
        assert line["infra"] == ["a"]
        assert line["canned_missing"] == {"b": 1}

    def test_ab_counts_infra_outside_the_pass_rate(self) -> None:
        from evals.ab import aggregate

        stats = aggregate([[{"id": "a", "pass": False, "score": 1, "infra": "live search failed"}]])
        assert stats["a"].infra == 1 and stats["a"].judged == 0


def test_a_live_case_failing_on_dead_search_is_infra(
    monkeypatch: pytest.MonkeyPatch, test_database: Any, test_user: Any
) -> None:
    from langchain_core.messages import AIMessage, ToolMessage

    import evals.run as eval_run
    from src.agent import agent as agent_module

    class DeadSearchAgent:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def chat_batch(self, **kwargs: Any) -> tuple[Any, ...]:
            dead = ToolMessage(
                name="web_search",
                content='{"query": "q", "results": [], "error": "No results found."}',
                tool_call_id="1",
            )
            return "I could not look it up.", [], {"tool_rounds": 1}, [dead]

    class FailingJudge:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def invoke(self, messages: list[Any]) -> AIMessage:
            return AIMessage(content='{"score": 1, "pass": false, "reasoning": "no price"}')

    monkeypatch.setattr(agent_module, "ChatAgent", DeadSearchAgent)
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", FailingJudge)
    live = EvalCase(id="l", description="", user="u", rubric="r", web="live")
    canned = EvalCase(id="c", description="", user="u", rubric="r")
    assert eval_run._run_case(live, test_user, test_database)["infra"] == "live search failed"
    assert "infra" not in eval_run._run_case(canned, test_user, test_database)
