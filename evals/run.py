#!/usr/bin/env python3
"""Agent eval harness: run golden cases through ChatAgent, judge with an LLM.

Each case is a YAML file in evals/cases/. A case runs single-turn against an
isolated temp database, deterministic checks run first (required/forbidden
tools, round caps), then an LLM judge scores the response against the rubric.

Informational, not a CI gate: run `make eval` before/after changing prompts,
tool descriptions, or the graph, and compare pass rates. Hits the live Gemini
API (a few cents per run).

Usage:
    make eval
    python evals/run.py [--only CASE_ID] [--cases evals/cases]
"""

import argparse
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

_JUDGE_INSTRUCTION = """You are grading an AI assistant's answer against a rubric.

Rubric: {rubric}

User asked: {user}

Assistant answered:
{response}

Tools the assistant actually called during the turn (tool calls are real
actions - e.g. kv_store listed here means stored data WAS updated; judge
persistence/actions by this list, not by the answer text):
{tools_called}

Sources the assistant formally cited via its citation tool (these are shown to
the user as source chips below the answer; citing this way COUNTS as citing):
{cited_sources}

Reply with ONLY a JSON object: {{"score": <1-5>, "pass": <true|false>, "reasoning": "<one sentence>"}}
Score 5 = fully satisfies the rubric; pass = score >= 3 AND no rubric requirement is missed."""


@dataclass
class EvalCase:
    """One golden eval case (see evals/cases/*.yaml)."""

    id: str
    description: str
    user: str
    requires: list[str] = field(default_factory=list)
    rubric: str = ""
    required_tools: list[str] = field(default_factory=list)  # any-of
    forbidden_tools: list[str] = field(default_factory=list)
    max_tool_rounds: int = 0  # 0 = no limit
    # Prior turns for multi-turn cases: [{role: user|assistant, content: str}]
    history: list[dict[str, str]] = field(default_factory=list)
    # "chat" (default) or "sports" (runs with a canned cycling program context)
    mode: str = "chat"
    # Sports mode: stored KV data injected into the program context
    program_kv: dict[str, str] = field(default_factory=dict)


def load_cases(directory: Path) -> list[EvalCase]:
    """Load and validate all YAML cases in a directory, sorted by id."""
    cases: list[EvalCase] = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        expect = data.get("expect") or {}
        if not (expect.get("rubric") or "").strip():
            raise ValueError(f"{path.name}: expect.rubric is required")
        cases.append(
            EvalCase(
                id=str(data["id"]),
                description=str(data.get("description", "")),
                user=str(data["user"]),
                requires=list(data.get("requires") or []),
                rubric=str(expect["rubric"]),
                required_tools=list(expect.get("required_tools") or []),
                forbidden_tools=list(expect.get("forbidden_tools") or []),
                max_tool_rounds=int(expect.get("max_tool_rounds") or 0),
                history=[
                    {"role": str(h["role"]), "content": str(h["content"])}
                    for h in (data.get("history") or [])
                ],
                mode=str(data.get("mode") or "chat"),
                program_kv={str(k): str(v) for k, v in (data.get("program_kv") or {}).items()},
            )
        )
    return cases


def parse_judge_response(text: str) -> tuple[int, bool, str]:
    """Extract (score, pass, reasoning) from the judge's reply; safe on garbage."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return 0, False, f"judge reply unparseable: {text[:120]}"
    try:
        data = json.loads(match.group(0))
        return (
            int(data.get("score", 0)),
            bool(data.get("pass", False)),
            str(data.get("reasoning", "")),
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0, False, f"judge reply unparseable: {text[:120]}"


def deterministic_failures(case: EvalCase, tools_used: set[str], tool_rounds: int) -> list[str]:
    """Rule-based checks that need no LLM. required_tools is any-of."""
    failures: list[str] = []
    if case.required_tools and not (set(case.required_tools) & tools_used):
        failures.append(
            f"none of the required tools {case.required_tools} were used ({sorted(tools_used) or 'no tools'})"
        )
    forbidden_used = set(case.forbidden_tools) & tools_used
    if forbidden_used:
        failures.append(f"forbidden tools used: {sorted(forbidden_used)}")
    if case.max_tool_rounds and tool_rounds > case.max_tool_rounds:
        failures.append(f"{tool_rounds} tool rounds > cap {case.max_tool_rounds}")
    return failures


def _requirements_met(case: EvalCase) -> bool:
    from src.agent.tools import is_browser_available, is_code_sandbox_available

    checks = {
        "code_sandbox": is_code_sandbox_available,
        "browser": is_browser_available,
    }
    return all(checks[req]() for req in case.requires if req in checks)


def _run_case(case: EvalCase, user: Any, db: Any) -> dict[str, Any]:
    """Execute one case through ChatAgent and judge it."""
    from langchain_core.messages import HumanMessage, ToolMessage

    from src.agent.agent import ChatAgent
    from src.agent.content import extract_cited_sources, extract_text_content
    from src.agent.tools.context import set_conversation_context
    from src.config import Config

    conversation = db.create_conversation(user.id, f"eval-{case.id}", model=Config.DEFAULT_MODEL)
    set_conversation_context(conversation.id, user.id)

    # Sports mode: canned cycling program (mirrors load_sports_context's shape)
    is_sports = case.mode == "sports"
    sports_context = None
    if is_sports:
        from src.agent.tools import set_sports_context

        sports_context = {
            "program_name": "Cyklistika",
            "program_id": "cycling",
            "kv_data": dict(case.program_kv),
        }
        set_sports_context("cycling")

    try:
        agent = ChatAgent(
            model_name=Config.DEFAULT_MODEL,
            is_sports=is_sports,
            sports_context=sports_context,
        )
        turn_started = time.monotonic()
        response, _tools, usage, result_messages = agent.chat_batch(
            text=case.user,
            history=case.history or None,
            user_name="Eval User",
            user_id=user.id,
            conversation_id=conversation.id,
            is_sports=is_sports,
            sports_context=sports_context,
        )
    finally:
        set_conversation_context(None, None)
        if is_sports:
            from src.agent.tools import set_sports_context

            set_sports_context(None)

    tools_used = {msg.name for msg in result_messages if isinstance(msg, ToolMessage) and msg.name}
    # cite_sources / set_conversation_title may be extract-only (never executed):
    # count requested tool calls too so required_tools can reference them
    for msg in result_messages:
        for tool_call in getattr(msg, "tool_calls", None) or []:
            if tool_call.get("name"):
                tools_used.add(tool_call["name"])

    tool_rounds = int(usage.get("tool_rounds", 0))
    failures = deterministic_failures(case, tools_used, tool_rounds)

    from langchain_google_genai import ChatGoogleGenerativeAI

    judge = ChatGoogleGenerativeAI(
        model=Config.EVAL_JUDGE_MODEL, google_api_key=Config.GEMINI_API_KEY, temperature=0.0
    )
    cited = extract_cited_sources(result_messages)
    judge_reply = judge.invoke(
        [
            HumanMessage(
                content=_JUDGE_INSTRUCTION.format(
                    rubric=case.rubric,
                    user=case.user,
                    response=response[:8000],
                    tools_called=", ".join(sorted(tools_used)) or "none",
                    cited_sources=json.dumps(cited, ensure_ascii=False) if cited else "none",
                )
            )
        ]
    )
    score, judge_pass, reasoning = parse_judge_response(extract_text_content(judge_reply.content))

    passed = judge_pass and not failures
    return {
        "id": case.id,
        "pass": passed,
        "score": score,
        "duration_s": round(time.monotonic() - turn_started, 1),
        "tool_rounds": tool_rounds,
        "tools_used": sorted(tools_used),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "deterministic_failures": failures,
        "judge_reasoning": reasoning,
        "response_preview": response[:200],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default=str(Path(__file__).parent / "cases"))
    parser.add_argument("--only", help="run a single case id")
    args = parser.parse_args()

    # Isolated temp DB + prod API key, BEFORE importing src.* (config reads env
    # at import). Migrations run automatically on Database init.
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")
    db_dir = tempfile.mkdtemp(prefix="evals-")
    os.environ["DATABASE_PATH"] = str(Path(db_dir) / "eval.db")
    os.environ["EMBEDDINGS_ENABLED"] = "false"  # keep eval runs cheap and focused

    # First src import in this process - the module-level db singleton (which
    # every agent tool uses) initializes against the temp DATABASE_PATH.
    from src.db.models import db

    user = db.get_or_create_user("eval@example.com", "Eval User")

    cases = load_cases(Path(args.cases))
    if args.only:
        cases = [case for case in cases if case.id == args.only]
        if not cases:
            print(f"No case with id={args.only}")
            return 1

    results: list[dict[str, Any]] = []
    for case in cases:
        if case.requires and not _requirements_met(case):
            print(f"SKIP  {case.id} (requires {case.requires})")
            results.append({"id": case.id, "skipped": True})
            continue
        print(f"RUN   {case.id} ...", flush=True)
        try:
            result = _run_case(case, user, db)
        except Exception as e:  # a crashed case is a failed case, not a dead run
            result = {"id": case.id, "pass": False, "score": 0, "error": str(e)}
        results.append(result)
        status = "PASS" if result.get("pass") else "FAIL"
        print(f"{status}  {case.id} score={result.get('score')} rounds={result.get('tool_rounds')} t={result.get('duration_s')}s")

    ran = [r for r in results if not r.get("skipped")]
    passed = sum(1 for r in ran if r.get("pass"))

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    from datetime import datetime

    out_path = results_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out_path.write_text(json.dumps({"results": results}, indent=2))

    print(f"\n{passed}/{len(ran)} passed ({len(results) - len(ran)} skipped)")
    print(f"Results: {out_path}")
    for r in ran:
        if not r.get("pass"):
            reason = "; ".join(r.get("deterministic_failures", [])) or r.get(
                "judge_reasoning", r.get("error", "")
            )
            print(f"  FAIL {r['id']}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
