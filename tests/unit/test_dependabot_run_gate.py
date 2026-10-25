"""Dependabot PRs merge only when Tests and the Dependency Audit passed (P3).

The auto-merge workflow feeds `gh run list` output for the PR's head commit
to .github/scripts/run_gate.py, once per workflow.
"""

import importlib.util
from pathlib import Path
from typing import Any

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "run_gate", Path(__file__).parents[2] / ".github" / "scripts" / "run_gate.py"
)
assert _SPEC and _SPEC.loader
run_gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(run_gate)


def _run(status: str, conclusion: str = "", created: str = "2026-10-25T10:00:00Z") -> Any:
    return {"status": status, "conclusion": conclusion, "createdAt": created}


@pytest.mark.parametrize(
    ("runs", "optional", "passed"),
    [
        ([_run("completed", "success")], False, True),
        ([_run("completed", "failure")], False, False),
        ([_run("in_progress")], False, False),
        ([_run("in_progress")], True, False),  # wait for the audit, don't skip it
        ([], False, False),  # Tests must have run
        ([], True, True),  # no lock file changed, so no audit
        (
            # A re-run decides, not the first attempt
            [
                _run("completed", "failure", "2026-10-25T10:00:00Z"),
                _run("completed", "success", "2026-10-25T11:00:00Z"),
            ],
            True,
            True,
        ),
        (
            [
                _run("completed", "success", "2026-10-25T10:00:00Z"),
                _run("completed", "failure", "2026-10-25T11:00:00Z"),
            ],
            True,
            False,
        ),
    ],
)
def test_gate(runs: list[dict[str, Any]], optional: bool, passed: bool) -> None:
    assert run_gate.gate(runs, optional)[0] is passed
