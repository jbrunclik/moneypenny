"""Tests for the eval harness (case loading + judge parsing + checks).

Only the pure pieces are tested here - actually running evals hits the live
Gemini API and happens via `make eval`, never in CI.
"""

from pathlib import Path

import pytest

from evals.run import EvalCase, deterministic_failures, load_cases, parse_judge_response


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
