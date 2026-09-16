"""Tests for the eval harness (case loading + judge parsing + checks).

Only the pure pieces are tested here - actually running evals hits the live
Gemini API and happens via `make eval`, never in CI.
"""

import json
from pathlib import Path

import pytest

from evals.run import (
    EvalCase,
    deterministic_failures,
    load_cases,
    parse_judge_response,
    run_with_timeout,
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
        )

    def test_required_tools_any_of(self) -> None:
        case = self._case(required_tools=["research", "web_search"])
        assert deterministic_failures(case, {"web_search"}, tool_rounds=1) == []
        assert deterministic_failures(case, {"fetch_url"}, tool_rounds=1)

    def test_forbidden_tools(self) -> None:
        case = self._case(forbidden_tools=["web_search"])
        assert deterministic_failures(case, {"web_search"}, tool_rounds=1)
        assert deterministic_failures(case, set(), tool_rounds=0) == []

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
