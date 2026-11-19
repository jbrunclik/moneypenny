"""A/B eval comparison across two commits (evals/ab.py): aggregation and report."""

from evals.ab import CaseStats, aggregate, format_report


def _run(*results: dict[str, object]) -> list[dict[str, object]]:
    return list(results)


def test_aggregate_counts_passes_scores_rounds_and_cost() -> None:
    runs = [
        _run({"id": "a", "pass": True, "score": 5, "tool_rounds": 1, "cost_usd": 0.04}),
        _run({"id": "a", "pass": False, "score": 2, "tool_rounds": 3, "cost_usd": 0.06}),
    ]

    stats = aggregate(runs)["a"]

    assert (stats.runs, stats.passed, stats.infra) == (2, 1, 0)
    assert stats.mean_score == 3.5
    assert stats.mean_rounds == 2.0
    assert round(stats.cost_usd, 2) == 0.10


def test_timeouts_and_crashes_are_infrastructure_not_failures() -> None:
    """A search outage or a hung case says nothing about the change: counted
    apart, and left out of the pass rate and the score."""
    runs = [
        _run(
            {"id": "a", "pass": False, "score": 0, "error": "case exceeded 300s", "timed_out": True}
        ),
        _run({"id": "a", "pass": False, "score": 0, "error": "ConnectionError"}),
        _run({"id": "a", "pass": True, "score": 4, "tool_rounds": 1, "cost_usd": 0.05}),
    ]

    stats = aggregate(runs)["a"]

    assert (stats.runs, stats.passed, stats.infra) == (3, 1, 2)
    assert stats.judged == 1
    assert stats.mean_score == 4.0


def test_skipped_cases_are_left_out() -> None:
    assert aggregate([_run({"id": "a", "skipped": True})]) == {}


def test_report_shows_both_sides_and_flags_a_changed_case() -> None:
    base = {"a": CaseStats(runs=2, passed=2, score_sum=10, judged=2, rounds_sum=2, cost_usd=0.1)}
    head = {"a": CaseStats(runs=2, passed=0, score_sum=4, judged=2, rounds_sum=6, cost_usd=0.2)}

    report = format_report(base, head, base_label="abc1234", head_label="working tree")

    assert "abc1234" in report and "working tree" in report
    line = next(row for row in report.splitlines() if row.lstrip().startswith("a "))
    assert "2/2" in line and "0/2" in line
    assert "<<" in line  # pass rate moved
    assert "$0.30" in report  # total spend of both sides


def test_report_marks_infrastructure_runs() -> None:
    base = {
        "a": CaseStats(
            runs=2, passed=1, score_sum=4, judged=1, rounds_sum=1, cost_usd=0.05, infra=1
        )
    }
    head = {"a": CaseStats(runs=2, passed=2, score_sum=9, judged=2, rounds_sum=2, cost_usd=0.1)}

    line = next(
        row
        for row in format_report(base, head, "b", "h").splitlines()
        if row.lstrip().startswith("a ")
    )
    assert "1 infra" in line


def test_each_side_runs_its_own_interpreter(tmp_path: object) -> None:
    """A dependency upgrade lives in its own venv: comparing it on the base's
    interpreter would test the old SDK twice."""
    from pathlib import Path

    from evals.ab import _python_for

    tree = Path(str(tmp_path))
    assert _python_for(tree, "/opt/py") == "/opt/py"
    (tree / ".venv" / "bin").mkdir(parents=True)
    (tree / ".venv" / "bin" / "python").write_text("")
    assert _python_for(tree, None) == str(tree / ".venv" / "bin" / "python")


def test_aggregate_counts_gate_low_runs() -> None:
    runs = [
        _run({"id": "a", "pass": True, "score": 5, "gate": {"thinking": "low", "lookup": False}}),
        _run({"id": "a", "pass": True, "score": 4, "gate": {"thinking": "low", "lookup": False}}),
        _run({"id": "b", "pass": False, "score": 2, "gate": {"thinking": "high", "lookup": True}}),
    ]
    stats = aggregate(runs)
    assert stats["a"].gate_low == 2
    assert stats["b"].gate_low == 0


def test_report_shows_the_gate_low_subset() -> None:
    low = CaseStats(runs=2, passed=2, score_sum=10, judged=2, gate_low=2)
    hard = CaseStats(runs=2, passed=0, score_sum=4, judged=2, gate_low=0)
    report = format_report({"a": low, "b": hard}, {"a": low, "b": hard}, "m1", "m2")
    assert "gate-low cases: 2/2 passed" in report


def test_model_sides_need_no_base() -> None:
    from evals.ab import parse_args

    args = parse_args(
        ["--model-a", "gemini-4-hydrogen", "--model-b", "gemini-4-carbon", "--only", "x"]
    )
    assert args.base is None and args.model_a == "gemini-4-hydrogen"


def test_same_model_on_both_sides_keeps_the_sides_apart() -> None:
    from evals.ab import _sides, parse_args

    args = parse_args(["--model-a", "m", "--model-b", "m", "--only", "x"])
    labels = [label for label, *_ in _sides(args)]
    assert len(set(labels)) == 2


def test_head_is_rejected_with_model_sides() -> None:
    import pytest

    from evals.ab import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--model-a", "a", "--model-b", "b", "--head", "HEAD", "--only", "x"])
