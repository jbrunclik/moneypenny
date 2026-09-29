#!/usr/bin/env python3
"""Agent eval harness: run golden cases through ChatAgent, judge with an LLM.

Each case is a YAML file in evals/cases/. A case runs single-turn against an
isolated temp database, deterministic checks run first (required/forbidden
tools, round caps), then an LLM judge scores the response against the rubric.

Informational, not a CI gate: run `make eval` before/after changing prompts,
tool descriptions, or the graph, and compare pass rates AND cost.

Hits the live Gemini API, so every run costs real money. Spend is measured
per case (agent tokens + any in-tool image/delegate spend, plus the LLM
judge, which is billed on a Pro model and is a substantial share), printed
in the summary, and persisted under "cost" in the results JSON so runs stay
comparable - a prompt change that holds the pass rate while doubling spend
is a regression that pass counts alone will not show.

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
import threading
import time
from collections.abc import Callable
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

Changes the assistant made through integrations during the turn (e.g. Todoist
tasks created/updated - judge actions by this list, not by the answer text):
{integration_changes}

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
    # Prior turns for multi-turn cases: [{role, content[, metadata]}] - metadata
    # is the enriched-history dict (e.g. tool_outputs) the model sees in MSG_CONTEXT
    history: list[dict[str, Any]] = field(default_factory=list)
    # Run the history through the real compaction pipeline first (summarizer
    # LLM calls included): older turns become the segmented summary, the recent
    # tail stays verbatim, and the summarized part is searchable - long-chat
    # memory end to end
    compact_history: bool = False
    # "chat" (default) or "sports" (runs with a canned cycling program context)
    mode: str = "chat"
    # Sports mode: stored KV data injected into the program context
    program_kv: dict[str, str] = field(default_factory=dict)
    # Attachment fixture paths, relative to evals/ (e.g. fixtures/sign.png)
    files: list[str] = field(default_factory=list)
    # Memories seeded before the case (soft-deleted after): [{content, category}]
    memories: list[dict[str, str]] = field(default_factory=list)
    # A past conversation seeded for episodic-recall cases:
    # {title: str, messages: [{role, content}]}
    seed_conversation: dict[str, Any] = field(default_factory=dict)
    # Fake integration backends (evals/fakes.py): {todoist: {...}, garmin: {...}}
    integrations: dict[str, Any] = field(default_factory=dict)


def _resolve_dates(value: Any) -> Any:
    """Replace {today}, {tomorrow}, {yesterday}, {in_N_days}, {N_days_ago}
    placeholders in fixture strings, so date-relative fixtures stay valid."""
    from datetime import date, timedelta

    if isinstance(value, dict):
        return {k: _resolve_dates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_dates(v) for v in value]
    if not isinstance(value, str):
        return value
    today = date.today()

    def sub(match: re.Match[str]) -> str:
        placeholder = match.group(1)
        if placeholder == "today":
            return today.isoformat()
        if placeholder == "tomorrow":
            return (today + timedelta(days=1)).isoformat()
        if placeholder == "yesterday":
            return (today - timedelta(days=1)).isoformat()
        if m := re.fullmatch(r"in_(\d+)_days", placeholder):
            return (today + timedelta(days=int(m.group(1)))).isoformat()
        if m := re.fullmatch(r"(\d+)_days_ago", placeholder):
            return (today - timedelta(days=int(m.group(1)))).isoformat()
        return match.group(0)

    return re.sub(r"\{([a-z0-9_]+)\}", sub, value)


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
                    {
                        "role": str(h["role"]),
                        "content": str(h["content"]),
                        **({"metadata": dict(h["metadata"])} if h.get("metadata") else {}),
                    }
                    for h in (data.get("history") or [])
                ],
                compact_history=bool(data.get("compact_history", False)),
                mode=str(data.get("mode") or "chat"),
                program_kv={str(k): str(v) for k, v in (data.get("program_kv") or {}).items()},
                files=[str(f) for f in (data.get("files") or [])],
                memories=[
                    {"content": str(m["content"]), "category": str(m.get("category", "fact"))}
                    for m in (data.get("memories") or [])
                ],
                seed_conversation=dict(data.get("seed_conversation") or {}),
                integrations=_resolve_dates(dict(data.get("integrations") or {})),
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


def _judge_tokens(reply: Any) -> tuple[int, int]:
    """(input, output) tokens for a judge call, 0 when the API omitted usage."""
    usage = getattr(reply, "usage_metadata", None)
    if not isinstance(usage, dict):
        return 0, 0
    return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))


def _turn_cost(model: str, usage: dict[str, Any], tool_results: list[dict[str, Any]]) -> float:
    """Cost of one agent turn, priced exactly as production prices a message.

    Deliberately reuses the same helpers as src/api/utils.record_message_cost
    rather than re-deriving the arithmetic, so an eval run's reported spend is
    directly comparable to real conversation costs (and any pricing change
    lands in both places at once). Covers the three components a turn can
    incur: its own tokens, images generated inside tools, and delegate_task
    subagent runs (which are billed at the subagent's own model).
    """
    from src.api.utils import (
        calculate_delegate_cost_from_tool_results,
        calculate_image_generation_cost_from_tool_results,
    )
    from src.utils.costs import calculate_total_cost

    return calculate_total_cost(
        model,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cached_input_tokens=int(usage.get("cached_input_tokens", 0)),
        image_generation_cost=calculate_image_generation_cost_from_tool_results(tool_results),
        tool_llm_cost=calculate_delegate_cost_from_tool_results(tool_results),
    )


def _usd(amount: float) -> str:
    """Format a USD amount, keeping sub-cent figures legible."""
    return f"${amount:.4f}" if amount < 0.01 else f"${amount:.2f}"


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


def run_with_timeout(fn: Callable[[], Any], timeout_s: float) -> Any:
    """Run `fn`, raising TimeoutError if it outlives `timeout_s`.

    Evals drive ChatAgent directly, and CHAT_TIMEOUT is enforced at the route
    layer, so nothing bounds a model call here: a stalled TLS read blocks the
    interpreter forever (observed Sep 15 2026 - 5h38m in _ssl__SSLSocket_read,
    forfeiting 27 finished cases).

    The worker is a daemon thread because a blocked socket read cannot be
    interrupted: on timeout we abandon it rather than join it, and being a
    daemon keeps it from holding the process open at exit.
    """
    outcome: dict[str, Any] = {}

    def _target() -> None:
        try:
            outcome["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - re-raised on the caller's thread
            outcome["error"] = e

    worker = threading.Thread(target=_target, daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        raise TimeoutError(f"case exceeded {timeout_s:.0f}s and was abandoned")
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


def _cost_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate spend over the cases that actually ran."""
    from src.config import Config

    ran = [r for r in results if not r.get("skipped")]

    def _sum(key: str) -> float:
        return sum(float(r.get(key) or 0) for r in ran)

    return {
        "agent_usd": round(_sum("agent_cost_usd"), 6),
        "judge_usd": round(_sum("judge_cost_usd"), 6),
        "total_usd": round(_sum("cost_usd"), 6),
        "agent_input_tokens": int(_sum("input_tokens")),
        "agent_output_tokens": int(_sum("output_tokens")),
        "agent_cached_input_tokens": int(_sum("cached_input_tokens")),
        "judge_input_tokens": int(_sum("judge_input_tokens")),
        "judge_output_tokens": int(_sum("judge_output_tokens")),
        "cases_priced": len(ran),
        "agent_model": Config.DEFAULT_MODEL,
        "judge_model": Config.EVAL_JUDGE_MODEL,
    }


def write_results(out_path: Path, results: list[dict[str, Any]]) -> None:
    """Persist results so far, overwriting the file.

    Called after EVERY case, not once at the end: a hang or a Ctrl-C used to
    forfeit the whole run's spend because nothing had been written yet.

    `cost` is persisted so runs stay comparable: a prompt change that keeps
    the pass rate but doubles spend is a regression you would not otherwise see.
    """
    out_path.write_text(json.dumps({"cost": _cost_summary(results), "results": results}, indent=2))


def _compacted_history(
    case: EvalCase, user: Any, db: Any, conversation_id: str
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Compact the case history exactly as production does for the next turn.

    Stores the history as the conversation's messages (so search can reach the
    summarized part), builds the segments with the real summarizer, persists
    them as the compaction state, and returns (history to send, summarizer
    token usage).
    """
    import json as _json
    from unittest.mock import patch

    from src.agent import compaction
    from src.agent.compaction_segments import extend_segments, render_segments
    from src.agent.conversation_compaction import KV_NAMESPACE, _summary_message
    from src.config import Config

    for turn in case.history:
        db.add_message(conversation_id, turn["role"], turn["content"])
    keep = Config.CONVERSATION_COMPACTION_KEEP_RECENT
    older, recent = case.history[:-keep], case.history[-keep:]

    usage = {"input": 0.0, "output": 0.0}
    original = compaction.run_summary_model

    def counted(prompt: str) -> str | None:
        # Rough token accounting for the summarizer's spend (~4 chars/token)
        text = original(prompt)
        usage["input"] += len(prompt) / 4
        usage["output"] += len(text or "") / 4
        return text

    with patch.object(compaction, "run_summary_model", counted):
        segments = extend_segments([], older, 0, len(older))
    if not segments:
        raise RuntimeError("compaction summarizer failed for the eval history")
    db.kv_set(
        user.id,
        KV_NAMESPACE,
        conversation_id,
        _json.dumps(
            {
                "segments": [{"text": s.text, "end": s.end, "passes": s.passes} for s in segments],
                "covered_count": segments[-1].end,
            }
        ),
    )
    return [_summary_message(render_segments(segments)), *recent], usage


def _run_case(case: EvalCase, user: Any, db: Any) -> dict[str, Any]:
    """Execute one case through ChatAgent and judge it."""
    from langchain_core.messages import HumanMessage, ToolMessage

    from src.agent.agent import ChatAgent
    from src.agent.content import extract_cited_sources, extract_text_content
    from src.agent.tools.context import set_conversation_context
    from src.config import Config

    conversation = db.create_conversation(user.id, f"eval-{case.id}", model=Config.DEFAULT_MODEL)
    set_conversation_context(conversation.id, user.id)
    # Per-turn tool bookkeeping (batching nudges, web_search -> research
    # upgrade) is keyed by request id; without one it is inert, so evals
    # used to measure round counts with every efficiency mechanism off
    import uuid

    from src.agent.tool_results import set_current_request_id

    set_current_request_id(f"eval-{case.id}-{uuid.uuid4().hex[:8]}")

    # Attachment fixtures -> the same shape the API layer hands to ChatAgent
    import base64
    import mimetypes

    files_payload = []
    for rel_path in case.files:
        fixture = Path(__file__).parent / rel_path
        files_payload.append(
            {
                "name": fixture.name,
                "type": mimetypes.guess_type(fixture.name)[0] or "application/octet-stream",
                "data": base64.b64encode(fixture.read_bytes()).decode(),
            }
        )

    # Seed memories (soft-deleted afterwards so they don't leak into later cases)
    seeded_memory_ids = [
        db.add_memory(user.id, m["content"], m.get("category") or "fact").id for m in case.memories
    ]

    # Seed a past conversation for episodic-recall cases
    if case.seed_conversation:
        past = db.create_conversation(
            user.id,
            str(case.seed_conversation.get("title", "Past chat")),
            model=Config.DEFAULT_MODEL,
        )
        for msg in case.seed_conversation.get("messages", []):
            db.add_message(past.id, str(msg["role"]), str(msg["content"]))

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

    history = case.history or None
    summarizer_usage = {"input": 0.0, "output": 0.0}
    if case.compact_history:
        history, summarizer_usage = _compacted_history(case, user, db, conversation.id)

    from evals.fakes import describe_actions, fake_integrations

    integration_changes = "none"
    try:
        agent = ChatAgent(
            model_name=Config.DEFAULT_MODEL,
            is_sports=is_sports,
            sports_context=sports_context,
        )
        turn_started = time.monotonic()
        # Fake integration backends replace only the HTTP/client seams, so
        # the real tool code runs (no-op when the case declares none)
        with fake_integrations(case.integrations) as fakes:
            # tool_results is needed for pricing: image generations and
            # delegate_task subagent tokens are only visible in there.
            response, tool_results, usage, result_messages = agent.chat_batch(
                text=case.user,
                files=files_payload or None,
                history=history,
                user_name="Eval User",
                user_id=user.id,
                conversation_id=conversation.id,
                is_sports=is_sports,
                sports_context=sports_context,
            )
            integration_changes = describe_actions(fakes)
    finally:
        set_conversation_context(None, None)
        from src.agent.tools.turn_usage import reset_turn_usage

        reset_turn_usage()
        set_current_request_id(None)
        if is_sports:
            from src.agent.tools import set_sports_context

            set_sports_context(None)
        for memory_id in seeded_memory_ids:
            db.delete_memory(memory_id, user.id)

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
                    integration_changes=integration_changes,
                )
            )
        ]
    )
    score, judge_pass, reasoning = parse_judge_response(extract_text_content(judge_reply.content))

    # The judge is a real billed API call - roughly a third of a run's spend,
    # since it re-sends the rubric plus the full response on a Pro model. It
    # went unmeasured before, so "a few cents per run" was a guess.
    from src.utils.costs import calculate_token_cost

    judge_input, judge_output = _judge_tokens(judge_reply)
    judge_cost = calculate_token_cost(Config.EVAL_JUDGE_MODEL, judge_input, judge_output)
    agent_cost = _turn_cost(Config.DEFAULT_MODEL, usage, tool_results)
    # Compaction cases also pay for building the summary (estimated tokens)
    agent_cost += calculate_token_cost(
        Config.AI_ASSIST_MODEL, int(summarizer_usage["input"]), int(summarizer_usage["output"])
    )

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
        "cached_input_tokens": usage.get("cached_input_tokens", 0),
        "judge_input_tokens": judge_input,
        "judge_output_tokens": judge_output,
        "agent_cost_usd": round(agent_cost, 6),
        "judge_cost_usd": round(judge_cost, 6),
        "cost_usd": round(agent_cost + judge_cost, 6),
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
    # Imported here, not at module scope: Config reads env at import time and
    # must not be loaded before the DATABASE_PATH override above.
    from src.config import Config
    from src.db.models import db

    user = db.get_or_create_user("eval@example.com", "Eval User")

    cases = load_cases(Path(args.cases))
    if args.only:
        cases = [case for case in cases if case.id == args.only]
        if not cases:
            print(f"No case with id={args.only}")
            return 1

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    from datetime import datetime

    out_path = results_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"

    results: list[dict[str, Any]] = []
    for case in cases:
        if case.requires and not _requirements_met(case):
            print(f"SKIP  {case.id} (requires {case.requires})")
            results.append({"id": case.id, "skipped": True})
            write_results(out_path, results)
            continue
        print(f"RUN   {case.id} ...", flush=True)
        try:
            result = run_with_timeout(
                lambda case=case: _run_case(case, user, db),  # type: ignore[misc]
                Config.EVAL_CASE_TIMEOUT_SECONDS,
            )
        except TimeoutError as e:
            # Abandoned, not retried: the worker thread is stuck in a socket
            # read we cannot interrupt, so the suite moves on without it.
            result = {"id": case.id, "pass": False, "score": 0, "error": str(e), "timed_out": True}
        except Exception as e:  # a crashed case is a failed case, not a dead run
            result = {"id": case.id, "pass": False, "score": 0, "error": str(e)}
        results.append(result)
        # Flush after every case so a hang or Ctrl-C keeps what was paid for
        write_results(out_path, results)
        status = "PASS" if result.get("pass") else "FAIL"
        cost = result.get("cost_usd")
        cost_str = f" cost={_usd(cost)}" if cost is not None else ""
        print(
            f"{status}  {case.id} score={result.get('score')} "
            f"rounds={result.get('tool_rounds')} t={result.get('duration_s')}s{cost_str}"
        )

    ran = [r for r in results if not r.get("skipped")]
    passed = sum(1 for r in ran if r.get("pass"))
    cost = _cost_summary(results)
    write_results(out_path, results)

    print(f"\n{passed}/{len(ran)} passed ({len(results) - len(ran)} skipped)")

    print(f"\nCost: {_usd(cost['total_usd'])} total for {len(ran)} cases")
    print(
        f"  agent ({cost['agent_model']}): {_usd(cost['agent_usd'])}  "
        f"{cost['agent_input_tokens']:,} in / {cost['agent_output_tokens']:,} out"
        + (
            f" ({cost['agent_cached_input_tokens']:,} cached)"
            if cost["agent_cached_input_tokens"]
            else ""
        )
    )
    print(
        f"  judge ({cost['judge_model']}): {_usd(cost['judge_usd'])}  "
        f"{cost['judge_input_tokens']:,} in / {cost['judge_output_tokens']:,} out"
    )
    if ran:
        priciest = max(ran, key=lambda r: float(r.get("cost_usd") or 0))
        print(
            f"  mean {_usd(cost['total_usd'] / len(ran))}/case, "
            f"priciest {priciest['id']} at {_usd(float(priciest.get('cost_usd') or 0))}"
        )
    if any(r.get("cost_usd") is None for r in ran):
        print("  NOTE: some cases errored before pricing; total is a lower bound.")

    print(f"\nResults: {out_path}")
    for r in ran:
        if not r.get("pass"):
            reason = "; ".join(r.get("deterministic_failures", [])) or r.get(
                "judge_reasoning", r.get("error", "")
            )
            print(f"  FAIL {r['id']}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
