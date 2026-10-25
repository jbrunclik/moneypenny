"""Did a workflow pass for the commit a Dependabot PR would merge? (P3)

Reads `gh run list --json status,conclusion,createdAt` output (the RUNS
environment variable, or stdin) for one workflow and one commit, and exits 0
only when its latest run completed successfully. With --optional, no run at
all also passes: the Dependency Audit runs only when a lock file changed, so
a GitHub Actions bump has none. A run still in progress does not pass - its
completion triggers the auto-merge job again.

Usage: run_gate.py [--optional] <workflow name for the log line>
"""

import json
import os
import sys
from typing import Any


def gate(runs: list[dict[str, Any]], optional: bool) -> tuple[bool, str]:
    if not runs:
        return optional, "no run" if optional else "no run yet"
    latest = max(runs, key=lambda run: run["createdAt"])
    if latest["status"] != "completed":
        return False, f"still {latest['status']}"
    return latest["conclusion"] == "success", str(latest["conclusion"])


if __name__ == "__main__":
    args = sys.argv[1:]
    optional = "--optional" in args
    name = " ".join(a for a in args if a != "--optional") or "workflow"
    passed, reason = gate(json.loads(os.environ.get("RUNS") or sys.stdin.read()), optional)
    print(f"{name}: {reason}")
    sys.exit(0 if passed else 1)
