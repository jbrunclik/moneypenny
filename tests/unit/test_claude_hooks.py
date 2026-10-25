"""The Claude Code hooks in .claude/hooks/ (agents are the main contributors).

guard-git.py protects parallel sessions sharing one checkout: a sweeping git
command (add -A, commit -a, stash, checkout .) takes or discards another
session's work. It also holds commits to Conventional Commits.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

_HOOK = Path(__file__).parents[2] / ".claude" / "hooks" / "guard-git.py"


def _run(command: str) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run(  # noqa: S603 - fixed interpreter and hook path
        [sys.executable, str(_HOOK)], input=payload, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize(
    "command",
    [
        "git add -A",
        "git add .",
        "git add --all && git commit -m 'fix: x'",
        "git add -u",
        "cd web && git add . ",
        "git commit -am 'fix: x'",
        "git commit -a -m 'fix: x'",
        "git stash",
        "git stash -q -- src/app.py",
        "git checkout -- .",
        "git checkout .",
        "git restore .",
        "git reset --hard",
        "git reset --hard origin/main",
        "git clean -fd",
    ],
)
def test_sweeping_commands_are_blocked(command: str) -> None:
    result = _run(command)
    assert result.returncode == 2, command
    assert "parallel" in result.stderr.lower() or "session" in result.stderr.lower()


@pytest.mark.parametrize(
    "command",
    [
        "git add src/app.py tests/unit/test_app.py",
        "git add web/src/utils/markdown.ts && git status --short",
        "git checkout src/db/models/planner.py",
        "git commit --amend --no-edit",
        "git stash list",
        "git status && git diff --stat",
        "ls -la .",
        "echo 'git add -A is blocked'",
    ],
)
def test_targeted_commands_pass(command: str) -> None:
    assert _run(command).returncode == 0, command


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m 'fix(planner): one planner per user'",
        'git commit -q -m "docs: update index"',
        "git commit -q -F - <<'EOF'\nrefactor(evals): split _run_case\n\nBody mentions git add -A.\nEOF",
        "git commit -m 'feat!: drop the v1 API'",
    ],
)
def test_conventional_messages_pass(command: str) -> None:
    assert _run(command).returncode == 0, command


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m 'Fixed the planner'",
        "git commit -m 'update stuff'",
        "git commit -F - <<'EOF'\nAdd a feature\n\nbody\nEOF",
        "git commit -m 'feature(ui): new thing'",
    ],
)
def test_non_conventional_messages_are_blocked(command: str) -> None:
    result = _run(command)
    assert result.returncode == 2, command
    assert "Conventional Commits" in result.stderr


def test_non_bash_payloads_pass() -> None:
    payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "x"}})
    result = subprocess.run(  # noqa: S603 - fixed interpreter and hook path
        [sys.executable, str(_HOOK)], input=payload, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
