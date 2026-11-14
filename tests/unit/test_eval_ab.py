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
