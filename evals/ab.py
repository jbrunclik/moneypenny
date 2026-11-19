"""A/B evals: the same cases on two versions of the code, compared per case.

Nov 2026: a prompt change was judged twice in one day by running a baseline
in a hand-made worktree and comparing case lists by eye; one case looked
like a regression on a single run and another failed on a search outage.
This runs the selected cases several times on each side - the base commit
in a temporary worktree, the head the current working tree (uncommitted
changes included) or another commit - alternating sides so provider drift
hits both, and reports per case: passes over runs, mean judge score, mean
tool rounds and spend. Timeouts and crashes are infrastructure, counted
apart and left out of the pass rate and score.

Nov 18 2026: it also compares two MODELS on the same code (--model-a,
--model-b; no base ref): the question before routing easy turns to a Lite
model. Each side reports its pass rate on the cases the freshness gate rated
easy ("low") too, since routing would only move those turns.

Usage:
    python evals/ab.py <base-ref> --only 'case_a,case_b' [--runs 2] [--head <ref>]
    python evals/ab.py --model-a gemini-4-hydrogen --model-b <lite> --only '*' [--runs 2]
Every run costs real money (the summary prints it): pick the affected cases.
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_WORKTREES = _ROOT / ".claude" / "worktrees"
# A pass rate this much apart, or a mean score this far, is worth a look
_PASS_RATE_FLAG = 0.5
_SCORE_FLAG = 1.0


@dataclass
class CaseStats:
    """One case's results on one side, over its runs."""

    runs: int = 0
    passed: int = 0
    score_sum: float = 0.0
    judged: int = 0  # runs that reached the judge (not infrastructure)
    rounds_sum: float = 0.0
    cost_usd: float = 0.0
    infra: int = 0
    gate_low: int = 0  # judged runs the freshness gate rated easy

    @property
    def mean_score(self) -> float:
        return self.score_sum / self.judged if self.judged else 0.0

    @property
    def mean_rounds(self) -> float:
        return self.rounds_sum / self.judged if self.judged else 0.0

    @property
    def pass_rate(self) -> float:
        return self.passed / self.judged if self.judged else 0.0


def _is_infra(result: dict[str, Any]) -> bool:
    """A timeout, a crash or a dead live search: the run says nothing about
    the code under test."""
    return bool(result.get("timed_out") or result.get("error") or result.get("infra"))


def aggregate(runs: list[list[dict[str, Any]]]) -> dict[str, CaseStats]:
    """Per-case stats over several runs' result lists."""
    stats: dict[str, CaseStats] = {}
    for results in runs:
        for result in results:
            if result.get("skipped"):
                continue
            case = stats.setdefault(str(result["id"]), CaseStats())
            case.runs += 1
            case.cost_usd += float(result.get("cost_usd") or 0)
            if _is_infra(result):
                case.infra += 1
                continue
            case.judged += 1
            case.gate_low += (result.get("gate") or {}).get("thinking") == "low"
            case.passed += bool(result.get("pass"))
            case.score_sum += float(result.get("score") or 0)
            case.rounds_sum += float(result.get("tool_rounds") or 0)
    return stats


def _cell(stats: CaseStats | None) -> str:
    if stats is None:
        return "-"
    infra = f", {stats.infra} infra" if stats.infra else ""
    return (
        f"{stats.passed}/{stats.judged} score {stats.mean_score:.1f} "
        f"rounds {stats.mean_rounds:.1f}{infra}"
    )


def _moved(base: CaseStats | None, head: CaseStats | None) -> bool:
    if base is None or head is None or not base.judged or not head.judged:
        return False
    return (
        abs(base.pass_rate - head.pass_rate) >= _PASS_RATE_FLAG
        or abs(base.mean_score - head.mean_score) >= _SCORE_FLAG
    )


def format_report(
    base: dict[str, CaseStats], head: dict[str, CaseStats], base_label: str, head_label: str
) -> str:
    """A table of both sides per case; `<<` marks a case that moved."""
    ids = sorted(set(base) | set(head))
    width = max([len(i) for i in ids] + [4])
    lines = [f"{'case':<{width}}  {base_label:<40}  {head_label}"]
    for case_id in ids:
        mark = "  <<" if _moved(base.get(case_id), head.get(case_id)) else ""
        lines.append(
            f"{case_id:<{width}}  {_cell(base.get(case_id)):<40}  {_cell(head.get(case_id))}{mark}"
        )
    for label, side in ((base_label, base), (head_label, head)):
        judged = sum(s.judged for s in side.values())
        passed = sum(s.passed for s in side.values())
        cost = sum(s.cost_usd for s in side.values())
        infra = sum(s.infra for s in side.values())
        lines.append(f"{label}: {passed}/{judged} passed, {infra} infra, ${cost:.2f}")
    for label, side in ((base_label, base), (head_label, head)):
        # A case counts as easy when the gate rated most of its runs low
        low = [s for s in side.values() if s.judged and s.gate_low * 2 > s.judged]
        passed = sum(s.passed for s in low)
        judged = sum(s.judged for s in low)
        lines.append(f"{label} gate-low cases: {passed}/{judged} passed ({len(low)} cases)")
    total = sum(s.cost_usd for side in (base, head) for s in side.values())
    lines.append(f"Total spend: ${total:.2f}")
    return "\n".join(lines)


def _worktree(ref: str) -> Path:
    """A detached worktree at `ref`, sharing this checkout's .env."""
    sha = subprocess.run(
        ["git", "rev-parse", "--short", ref], cwd=_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    path = _WORKTREES / f"eval-ab-{sha}"
    if not path.exists():
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(path), ref], cwd=_ROOT, check=True
        )
        (path / ".env").symlink_to(_ROOT / ".env")
    return path


def _python_for(tree: Path, override: str | None) -> str:
    """The interpreter for a side: given, else the tree's own .venv, else this one
    (a dependency upgrade lives in its own venv - both sides must not share one)."""
    if override:
        return override
    own = tree / ".venv" / "bin" / "python"
    return str(own) if own.exists() else sys.executable


def _run_side(
    tree: Path, python: str, only: str, workers: int | None, model: str | None = None
) -> list[dict[str, Any]]:
    """One eval run in `tree`; its results (empty when the run died).

    The run's results file is the one it adds to the tree's evals/results -
    every commit's runner writes there, so an older base needs no new flag.
    """
    results_dir = tree / "evals" / "results"
    before = set(results_dir.glob("*.json")) if results_dir.exists() else set()
    command = [python, "evals/run.py", "--only", only]
    if workers:
        command += ["--workers", str(workers)]
    env = {**os.environ, "PYTHONPATH": str(tree)}
    if model:
        command += ["--model", model]
    subprocess.run(command, cwd=tree, env=env, check=False)
    new = sorted(set(results_dir.glob("*.json")) - before) if results_dir.exists() else []
    if not new:
        return []
    results: list[dict[str, Any]] = json.loads(new[-1].read_text())["results"]
    return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "base", nargs="?", help="the commit to compare against (omit with --model-a/--model-b)"
    )
    parser.add_argument("--head", help="a commit for the other side (default: the working tree)")
    parser.add_argument("--model-a", help="chat model for side A (both sides: the working tree)")
    parser.add_argument("--model-b", help="chat model for side B")
    parser.add_argument("--only", required=True, help="case ids or globs, comma-separated")
    parser.add_argument("--runs", type=int, default=2, help="runs per side (default 2)")
    parser.add_argument("--workers", type=int, help="parallel cases per run")
    parser.add_argument("--keep", action="store_true", help="keep the worktrees afterwards")
    parser.add_argument(
        "--base-python", help="interpreter for the base (default: its .venv, else this one)"
    )
    parser.add_argument(
        "--head-python", help="interpreter for the head (default: its .venv, else this one)"
    )
    args = parser.parse_args(argv)
    by_model = bool(args.model_a or args.model_b)
    if by_model and not (args.model_a and args.model_b):
        parser.error("--model-a and --model-b go together")
    if by_model == bool(args.base):
        parser.error("give either a base ref or --model-a/--model-b")
    if by_model and args.head:
        parser.error("--head compares commits; model sides both run the working tree")
    return args


def _sides(args: argparse.Namespace) -> list[tuple[str, Path, str | None, str | None]]:
    """(label, tree, model, python override) for side A then side B."""
    if args.model_a:
        same = args.model_a == args.model_b  # a noise check: keep the sides apart
        return [
            (
                f"{args.model_a} (A)" if same else args.model_a,
                _ROOT,
                args.model_a,
                args.head_python,
            ),
            (
                f"{args.model_b} (B)" if same else args.model_b,
                _ROOT,
                args.model_b,
                args.head_python,
            ),
        ]
    head = _worktree(args.head) if args.head else _ROOT
    return [
        (args.base, _worktree(args.base), None, args.base_python),
        (args.head or "working tree", head, None, args.head_python),
    ]


def main() -> int:
    args = parse_args()
    sides = _sides(args)
    runs: dict[str, list[list[dict[str, Any]]]] = {label: [] for label, *_ in sides}
    for run in range(args.runs):
        # Alternate sides so provider drift over the night hits both
        for label, tree, model, override in sides if run % 2 == 0 else sides[::-1]:
            python = _python_for(tree, override)
            print(f"\n=== {label} run {run + 1}/{args.runs} ({tree.name}, {python})", flush=True)
            runs[label].append(_run_side(tree, python, args.only, args.workers, model))

    (a_label, *_), (b_label, *_) = sides
    report = format_report(aggregate(runs[a_label]), aggregate(runs[b_label]), a_label, b_label)
    print("\n" + report)
    if not args.keep:
        for tree in {tree for _, tree, *_ in sides} - {_ROOT}:
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=_ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
