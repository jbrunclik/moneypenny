#!/usr/bin/env python3
"""Remove the agent worktrees left under .claude/worktrees (make clean-worktrees).

Subagent runs leave a worktree and a branch each; in two days of Oct 2026
they reached 54 worktrees and 8.3 GB, and repo-wide greps kept hitting their
copies. A worktree goes when nothing holds it:

- a lock (a running Claude session holds its agents' worktrees) keeps it;
- uncommitted changes keep it, unless `--force` (they are usually a
  subagent's build output, but say so before discarding them);
- the gate worktree (`gate-clean`) and anything outside .claude/worktrees
  are never touched.

Its branch is deleted only when every commit is already in origin/main
(`git cherry`), so work that never landed survives as a branch.

    python scripts/clean_worktrees.py [--force] [--dry-run]
"""

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKTREES = ROOT / ".claude" / "worktrees"
KEEP = {"gate-clean"}


@dataclass
class Worktree:
    path: Path
    branch: str | None
    locked: bool


def _git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _worktrees() -> list[Worktree]:
    found: list[Worktree] = []
    for block in _git("worktree", "list", "--porcelain").strip().split("\n\n"):
        fields = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            fields[key] = value
        path = Path(fields["worktree"])
        if path.parent != WORKTREES or path.name in KEEP:
            continue
        branch = fields.get("branch", "").removeprefix("refs/heads/") or None
        found.append(Worktree(path, branch, "locked" in fields))
    return found


def _landed(branch: str) -> bool:
    return not any(
        line.startswith("+") for line in _git("cherry", "origin/main", branch).splitlines()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--force", action="store_true", help="also remove worktrees with changes")
    parser.add_argument("--dry-run", action="store_true", help="report, change nothing")
    args = parser.parse_args()

    _git("fetch", "-q", "origin", "main")
    removed = kept = branches = 0
    for tree in _worktrees():
        dirty = bool(_git("status", "--porcelain", cwd=tree.path).strip())
        if tree.locked or (dirty and not args.force):
            reason = "locked" if tree.locked else "uncommitted changes (--force removes them)"
            print(f"keep   {tree.path.name}: {reason}")
            kept += 1
            continue
        print(f"remove {tree.path.name}" + (" (with its changes)" if dirty else ""))
        removed += 1
        if args.dry_run:
            continue
        _git("worktree", "remove", "--force", str(tree.path))
        if tree.branch and _landed(tree.branch):
            _git("branch", "-D", "-q", tree.branch)
            branches += 1
        elif tree.branch:
            print(f"       branch {tree.branch} kept: it has commits not in origin/main")
    if not args.dry_run:
        _git("worktree", "prune")
    print(f"{removed} removed, {kept} kept, {branches} landed branches deleted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
