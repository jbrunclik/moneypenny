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

Cases run in parallel worker processes (--workers, default EVAL_WORKERS),
each with its own temp database; results are reported in case order.

Usage:
    make eval
    python evals/run.py [--only 'ID_OR_GLOB[,...]'] [--workers N] [--cases evals/cases]
"""

import argparse
import contextlib
import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from evals.chats import load_chat, merge_chat, seed_frozen_summary
from evals.fakes import describe_recorded
from src.utils.clock import local_today, to_local, utc_now

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

_JUDGE_INSTRUCTION = """You are grading an AI assistant's answer against a rubric.

Rubric: {rubric}

User asked: {user}

Assistant answered:
{response}

(Bracketed tags in the answer - [UNSOURCED: ...], [PARTLY SOURCED: ...],
[CONTRADICTED BY SOURCE: ...], [source N] - were inserted by the grading
harness after the claim they judge: they are the grounding check's verdicts,
shown to the user as underlines, not text the assistant wrote. Grade the
claims they mark; never fail the answer for "leaking" them.)

Tools the assistant actually called during the turn (tool calls are real
actions - e.g. kv_store listed here means stored data WAS updated; judge
persistence/actions by this list, not by the answer text):
{tools_called}

Sources shown to the user as source links below the answer (derived
automatically from the pages the assistant read - this COUNTS as citing):
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
    # In the ~$1 smoke subset (`--smoke`, `make eval-smoke`)
    smoke: bool = False
    # A behaviour the agent does not have yet (a target, not a regression):
    # reported as TARGET instead of FAIL, so a run's failures are the new ones
    known_failure: str | None = None
    rubric: str = ""
    required_tools: list[str] = field(default_factory=list)  # any-of
    forbidden_tools: list[str] = field(default_factory=list)
    max_tool_rounds: int = 0  # 0 = no limit
    # load_skill must have been called with THIS skill name (required_tools
    # only proves some load_skill call happened)
    required_skill: str | None = None
    # Regexes that must NOT match a tool argument, keyed "tool.arg" (e.g.
    # create_artifact.html: hex colours) - the judge never sees tool args
    forbidden_arg_patterns: dict[str, list[str]] = field(default_factory=dict)
    # Regexes that must each match the argument of at least one call to that
    # tool, keyed "tool.arg" (e.g. manage_memory.operations: a valid_until)
    required_arg_patterns: dict[str, list[str]] = field(default_factory=dict)
    # Regexes that must each match an action a fake recorded, keyed by fake
    # (todoist, garmin, calendar): the write a turn must make, checked
    # without the judge (e.g. garmin: ["^updated workout"])
    required_actions: dict[str, list[str]] = field(default_factory=dict)
    # Prior turns for multi-turn cases: [{role, content[, metadata]}] - metadata
    # is the enriched-history dict (e.g. tool_outputs) the model sees in MSG_CONTEXT
    history: list[dict[str, Any]] = field(default_factory=list)
    # Run the history through the real compaction pipeline first (summarizer
    # LLM calls included): older turns become the segmented summary, the recent
    # tail stays verbatim, and the summarized part is searchable - long-chat
    # memory end to end
    compact_history: bool = False
    # "chat" (default), "sports" / "language" (a canned program chat - cycling /
    # Italian; program_kv is its stored data) or "agent" (a canned agent's chat)
    mode: str = "chat"
    # Sports mode: stored KV data injected into the program context
    program_kv: dict[str, str] = field(default_factory=dict)
    # The program a sports/language chat runs as ({id, name}); default the
    # canned one for the mode (cycling / Italian)
    program: dict[str, str] = field(default_factory=dict)
    # Save the history's user turns and the case's message in the chat (dated
    # now), as production saves them before the turn: tools that check what
    # the user wrote in this chat (propose_instruction_change evidence) see them
    save_user_turns: bool = False
    # Attachment fixture paths, relative to evals/ (e.g. fixtures/sign.png)
    files: list[str] = field(default_factory=list)
    # Memories seeded before the case (soft-deleted after): [{content, category}]
    memories: list[dict[str, str]] = field(default_factory=list)
    # Artifacts seeded in the case's conversation: [{title, html}]; their ids
    # replace {artifact_0}, {artifact_1}... in the history (revision cases)
    # {title, html, state?}: state is the saved envelope ({app, checklist})
    artifacts: list[dict[str, object]] = field(default_factory=list)
    # A past conversation seeded for episodic-recall cases:
    # {title: str, messages: [{role, content}]}
    seed_conversation: dict[str, Any] = field(default_factory=dict)
    # Round backstop for this case's turn (None: TURN_MAX_TOOL_ROUNDS) - to
    # exercise what a stopped answer says
    round_cap: int | None = None
    # KV rows seeded for the user: [{namespace, key, value}]; {conversation_id}
    # in a key is the case's conversation
    kv: list[dict[str, str]] = field(default_factory=list)
    # Proposal cards pending on the history's last reply: [{kind, summary,
    # details, label, payload}]; the case's user message answers them before
    # the turn, as the chat route does (src/agent/proposals.py answer_and_note)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    # Fake integration backends (evals/fakes.py): {todoist: {...}, garmin: {...}}
    integrations: dict[str, Any] = field(default_factory=dict)
    # Canned web ({results, pages}; None = canned with no results) or "live"
    # for the real ddgs path (evals/fake_web.py)
    web: dict[str, Any] | str | None = None
    # Run the deep-research pipeline with this plan instead of a chat turn:
    # {question, context, sub_questions} (the offer step has its own cases)
    deep_research: dict[str, Any] = field(default_factory=dict)
    # Settled conversation facts ([{key, text}], [] for an empty list): the
    # case runs with CONVERSATION_FACTS_ENABLED on; None leaves it off
    conversation_facts: list[dict[str, str]] | None = None
    # The background memory review instead of an agent turn: the history plus
    # `user` are reviewed, the ops it applied graded as one manage_memory call
    memory_review: bool = False
    # A shared synthetic chat (evals/chats.py) whose messages precede `history`
    history_from: str | None = None
    # That chat's frozen compaction summary of its older turns, and how many of
    # the chat's messages it covers
    frozen_summary: str | None = None
    frozen_summary_covers: int | None = None


_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _placeholder_date(placeholder: str, today: date) -> date | None:
    """The day a date placeholder names ("today", "in_3_days"...), or None."""
    if placeholder == "today":
        return today
    if placeholder == "tomorrow":
        return today + timedelta(days=1)
    if placeholder == "yesterday":
        return today - timedelta(days=1)
    if m := re.fullmatch(r"in_(\d+)_days", placeholder):
        return today + timedelta(days=int(m.group(1)))
    if m := re.fullmatch(r"(\d+)_days_ago", placeholder):
        return today - timedelta(days=int(m.group(1)))
    if m := re.fullmatch(rf"({'|'.join(_WEEKDAYS)})(?:_plus_(\d+))?", placeholder):
        # The next such weekday after today (prose that says "on Tuesday")
        ahead = (_WEEKDAYS.index(m.group(1)) - today.weekday() - 1) % 7 + 1
        return today + timedelta(days=ahead + int(m.group(2) or 0))
    return None


_CZECH_WEEKDAYS = ("pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle")


def _english_weekday(day: date) -> str:
    return day.strftime("%A")


def _english_long(day: date) -> str:
    """ "Tuesday 24 November" - how a notice or an email names a day."""
    return f"{day.strftime('%A')} {day.day} {day.strftime('%B')}"


def _czech_weekday(day: date) -> str:
    return _CZECH_WEEKDAYS[day.weekday()]


def _resolve_dates(value: Any) -> Any:
    """Replace {today}, {tomorrow}, {yesterday}, {in_N_days}, {N_days_ago}
    placeholders in fixture strings, so date-relative fixtures stay valid.
    A `_weekday` suffix ({today_weekday}) gives the English weekday name,
    `_long` ({tuesday_long}) "Tuesday 24 November", `_cs` ({tomorrow_cs}) the
    Czech weekday - prose that names days then agrees
    with the fixture's dates whatever day the suite runs."""
    if isinstance(value, dict):
        return {k: _resolve_dates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_dates(v) for v in value]
    if not isinstance(value, str):
        return value
    today = local_today()

    def sub(match: re.Match[str]) -> str:
        placeholder = match.group(1)
        for suffix, name in (
            ("_weekday", _english_weekday),
            ("_cs", _czech_weekday),
            ("_long", _english_long),
        ):
            if placeholder.endswith(suffix):
                day = _placeholder_date(placeholder.removesuffix(suffix), today)
                return name(day) if day else match.group(0)
        day = _placeholder_date(placeholder, today)
        return day.isoformat() if day else match.group(0)

    return re.sub(r"\{([a-z0-9_]+)\}", sub, value)


def _parse_history(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A case's prior turns, date placeholders resolved in content and metadata."""
    return [
        {
            "role": str(h["role"]),
            "content": _resolve_dates(str(h["content"])),
            **({"metadata": _resolve_dates(dict(h["metadata"]))} if h.get("metadata") else {}),
            **({"files": [str(f) for f in h["files"]]} if h.get("files") else {}),
        }
        for h in raw
    ]


def load_cases(directory: Path) -> list[EvalCase]:
    """Load and validate all YAML cases in a directory, sorted by id."""
    cases: list[EvalCase] = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if data.get("history_from"):
            try:
                data = merge_chat(data, load_chat(str(data["history_from"])))
            except ValueError as e:
                raise ValueError(f"{path.name}: {e}") from e
        expect = data.get("expect") or {}
        if not (expect.get("rubric") or "").strip():
            raise ValueError(f"{path.name}: expect.rubric is required")
        cases.append(
            EvalCase(
                id=str(data["id"]),
                description=str(data.get("description", "")),
                user=_resolve_dates(str(data["user"])),
                requires=list(data.get("requires") or []),
                smoke=bool(data.get("smoke", False)),
                known_failure=str(data["known_failure"]) if data.get("known_failure") else None,
                rubric=_resolve_dates(str(expect["rubric"])),
                required_tools=list(expect.get("required_tools") or []),
                forbidden_tools=list(expect.get("forbidden_tools") or []),
                max_tool_rounds=int(expect.get("max_tool_rounds") or 0),
                required_skill=expect.get("required_skill"),
                forbidden_arg_patterns={
                    str(k): [str(p) for p in v]
                    for k, v in (expect.get("forbidden_arg_patterns") or {}).items()
                },
                required_arg_patterns={
                    str(k): [str(p) for p in v]
                    for k, v in (expect.get("required_arg_patterns") or {}).items()
                },
                required_actions={
                    str(k): [str(p) for p in v]
                    for k, v in (expect.get("required_actions") or {}).items()
                },
                history=_parse_history(data.get("history") or []),
                compact_history=bool(data.get("compact_history", False)),
                mode=str(data.get("mode") or "chat"),
                program_kv={str(k): str(v) for k, v in (data.get("program_kv") or {}).items()},
                program={str(k): str(v) for k, v in (data.get("program") or {}).items()},
                save_user_turns=bool(data.get("save_user_turns", False)),
                files=[str(f) for f in (data.get("files") or [])],
                memories=[
                    {"content": str(m["content"]), "category": str(m.get("category", "fact"))}
                    | ({"summary": str(m["summary"])} if m.get("summary") else {})
                    for m in (data.get("memories") or [])
                ],
                artifacts=[
                    {"title": str(a["title"]), "html": str(a["html"])}
                    | ({"state": a["state"]} if a.get("state") is not None else {})
                    for a in (data.get("artifacts") or [])
                ],
                seed_conversation=dict(data.get("seed_conversation") or {}),
                round_cap=int(data["round_cap"]) if data.get("round_cap") else None,
                kv=[
                    {
                        "namespace": str(e["namespace"]),
                        "key": str(e["key"]),
                        "value": str(e["value"]),
                    }
                    for e in (data.get("kv") or [])
                ],
                proposals=[dict(p) for p in (data.get("proposals") or [])],
                integrations=_resolve_dates(dict(data.get("integrations") or {})),
                web=_web_spec(data.get("web")),
                memory_review=bool(data.get("memory_review", False)),
                history_from=str(data["history_from"]) if data.get("history_from") else None,
                frozen_summary=(
                    str(data["frozen_summary"]) if data.get("frozen_summary") else None
                ),
                frozen_summary_covers=(
                    int(data["frozen_summary_covers"])
                    if data.get("frozen_summary_covers") is not None
                    else None
                ),
                deep_research=dict(data.get("deep_research") or {}),
                conversation_facts=(
                    None
                    if data.get("conversation_facts") is None
                    else [
                        {"key": str(f["key"]), "text": str(f["text"])}
                        for f in data["conversation_facts"]
                    ]
                ),
            )
        )
    return cases


def _web_spec(raw: Any) -> dict[str, Any] | str | None:
    if raw is None or raw == "live":
        return raw  # type: ignore[no-any-return]
    if not isinstance(raw, dict):
        raise ValueError(f"web must be 'live' or {{results, pages}}, got {raw!r}")
    spec: dict[str, Any] = _resolve_dates(raw)
    return spec


def with_artifact_ids(history: list[dict[str, Any]], ids: list[str]) -> list[dict[str, Any]]:
    """The history with {artifact_N} replaced by the seeded artifacts' ids."""

    def fill(value: Any) -> Any:
        if isinstance(value, str):
            for i, art_id in enumerate(ids):
                value = value.replace(f"{{artifact_{i}}}", art_id)
            return value
        if isinstance(value, dict):
            return {k: fill(v) for k, v in value.items()}
        return value

    return [fill(turn) for turn in history]


def select_cases(cases: list[EvalCase], patterns: list[str]) -> list[EvalCase]:
    """Cases matching any id or glob (comma-separated allowed), in case order.

    No patterns keeps every case. A pattern that matches nothing is an error -
    a typo must not silently shrink a rerun.
    """
    wanted = [p.strip() for raw in patterns for p in raw.split(",") if p.strip()]
    if not wanted:
        return cases
    unmatched = [p for p in wanted if not any(fnmatch.fnmatchcase(c.id, p) for c in cases)]
    if unmatched:
        raise ValueError(f"no case matches: {', '.join(unmatched)}")
    return [c for c in cases if any(fnmatch.fnmatchcase(c.id, p) for p in wanted)]


def in_case_order(cases: list[EvalCase], done: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Finished results in case order (workers finish out of order)."""
    return [done[c.id] for c in cases if c.id in done]


_JUDGE_LABELS = {
    "not_found": "UNSOURCED",
    "partial": "PARTLY SOURCED",
    "contradicted": "CONTRADICTED BY SOURCE",
}


def _judge_tag(ann: dict[str, Any]) -> str:
    if ann.get("verdict") == "supported":
        return f" [source {ann['source']}]" if ann.get("source") else ""
    reason = f": {ann['reason']}" if ann.get("reason") else ""
    return f" [{_JUDGE_LABELS.get(ann.get('verdict', ''), 'UNSOURCED')}{reason}]"


# What the judge reads of a response. 8000 until Nov 19 2026: a 1,500-word
# deep-research report with the grounding tags runs past it, and the judge
# failed it for "cutting off mid-word" - a cut the user never sees
JUDGE_RESPONSE_MAX_CHARS = 20_000
_UNSUPPORTED_VERDICTS = ("not_found", "partial", "contradicted")
_SUMMARY_QUOTE_CHARS = 80


def grounding_summary(usage: dict[str, Any]) -> dict[str, Any] | None:
    """The grounding check's verdict counts and its unsupported quotes, for the
    result row (how much of a report its pages backed); None when unchecked."""
    grounding = usage.get("grounding")
    if not grounding:
        return None
    annotations = [a for a in grounding.get("annotations") or [] if isinstance(a, dict)]
    return {
        "counts": dict(Counter(str(a.get("verdict")) for a in annotations)),
        "unsupported": [
            str(a.get("quote", ""))[:_SUMMARY_QUOTE_CHARS]
            for a in annotations
            if a.get("verdict") in _UNSUPPORTED_VERDICTS
        ],
    }


def annotate_for_judge(response: str, grounding: dict[str, Any] | None) -> str:
    """The answer with each claim's verdict right after it, as users see it.

    The UI underlines a claim where it stands; an end-of-answer list was
    measured not to work (the reader, and the judge, take the text as fact).
    """
    text = response
    for ann in (grounding or {}).get("annotations") or []:
        tag = _judge_tag(ann)
        start = text.find(ann.get("quote", "")) if tag else -1
        if start >= 0:
            end = start + len(ann["quote"])
            text = text[:end] + tag + text[end:]
    return text


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
    except json.JSONDecodeError, TypeError, ValueError:
        return 0, False, f"judge reply unparseable: {text[:120]}"


def _judge_tokens(reply: Any) -> tuple[int, int]:
    """(input, output) tokens for a judge call, 0 when the API omitted usage."""
    usage = getattr(reply, "usage_metadata", None)
    if not isinstance(usage, dict):
        return 0, 0
    return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))


def turn_cost(model: str, usage: dict[str, Any], tool_results: list[dict[str, Any]]) -> float:
    """Cost of one agent turn, priced exactly as production prices a message.

    Deliberately reuses the same helpers as src/api/utils.record_message_cost
    rather than re-deriving the arithmetic, so an eval run's reported spend is
    directly comparable to real conversation costs (and any pricing change
    lands in both places at once). Covers the four components a turn can
    incur: its own tokens, images generated inside tools, and delegate_task
    subagent runs (which are billed at the subagent's own model), and the
    post-answer grounding check (priced at its own model). A deep-research
    report is priced at its writer, plus its research subagents.
    """
    from src.services.costs import (
        calculate_deep_research_cost,
        calculate_delegate_cost_from_tool_results,
        calculate_freshness_cost,
        calculate_grounding_cost,
        calculate_image_generation_cost_from_tool_results,
        calculate_total_cost,
    )

    return calculate_total_cost(
        usage.get("answer_model") or model,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cached_input_tokens=int(usage.get("cached_input_tokens", 0)),
        image_generation_cost=calculate_image_generation_cost_from_tool_results(tool_results),
        tool_llm_cost=calculate_delegate_cost_from_tool_results(tool_results)
        + calculate_grounding_cost(usage)
        + calculate_freshness_cost(usage)
        + calculate_deep_research_cost(usage),
    )


def run_deep_research_turn(
    spec: dict[str, Any], request_id: str
) -> tuple[str, list[dict[str, Any]], dict[str, Any], list[Any]]:
    """Run the deep-research pipeline on a case's plan; chat_batch's shape."""
    from src.agent.deep_research import pipeline
    from src.agent.deep_research.estimate import estimate
    from src.agent.deep_research.plan import DeepResearchPlan

    items = [str(q) for q in spec["sub_questions"]]
    plan = DeepResearchPlan(
        offer_message_id="eval",
        question=str(spec.get("question", "")),
        context=str(spec.get("context", "")),
        sub_questions=items,
        offered_sub_questions=items,
        estimate=estimate(len(items)),
    )
    final: dict[str, Any] = {}
    for event in pipeline.run_deep_research(plan, "", request_id):
        if event.get("type") == "final":
            final = event
    return (
        str(final.get("content", "")),
        list(final.get("tool_results") or []),
        dict(final.get("usage_info") or {}),
        list(final.get("result_messages") or []),
    )


def _usd(amount: float) -> str:
    """Format a USD amount, keeping sub-cent figures legible."""
    return f"${amount:.4f}" if amount < 0.01 else f"${amount:.2f}"


def skills_loaded_in(messages: list[Any]) -> set[str]:
    """Skill names passed to load_skill calls in the turn's messages."""
    return {
        str(call.get("args", {}).get("name", ""))
        for msg in messages
        for call in getattr(msg, "tool_calls", None) or []
        if call.get("name") == "load_skill"
    }


def tool_calls_in(messages: list[Any]) -> list[dict[str, Any]]:
    """Every tool call ({name, args}) requested in the turn's messages."""
    return [
        {"name": call.get("name"), "args": call.get("args") or {}}
        for msg in messages
        for call in getattr(msg, "tool_calls", None) or []
    ]


def _arg_pattern_failures(case: EvalCase, tool_calls: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for key, patterns in case.forbidden_arg_patterns.items():
        tool_name, _, arg = key.partition(".")
        for call in tool_calls:
            value = str(call["args"].get(arg, "")) if call["name"] == tool_name else ""
            hits = [p for p in patterns if value and re.search(p, value)]
            if hits:
                failures.append(f"{key} matched forbidden pattern(s) {hits}")
    for key, patterns in case.required_arg_patterns.items():
        tool_name, _, arg = key.partition(".")
        values = [str(c["args"].get(arg, "")) for c in tool_calls if c["name"] == tool_name]
        missing = [p for p in patterns if not any(re.search(p, v) for v in values)]
        if missing:
            failures.append(f"{key} matched no call for required pattern(s) {missing}")
    return failures


def _action_failures(case: EvalCase, actions: dict[str, list[str]]) -> list[str]:
    failures: list[str] = []
    for fake, patterns in case.required_actions.items():
        recorded = actions.get(fake) or []
        missing = [p for p in patterns if not any(re.search(p, a) for a in recorded)]
        if missing:
            failures.append(
                f"{fake} recorded no action matching {missing} ({len(recorded)} recorded)"
            )
    return failures


def deterministic_failures(
    case: EvalCase,
    tools_used: set[str],
    tool_rounds: int,
    skills_loaded: set[str] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    actions: dict[str, list[str]] | None = None,
) -> list[str]:
    """Rule-based checks that need no LLM. required_tools is any-of."""
    failures: list[str] = _arg_pattern_failures(case, tool_calls or [])
    failures += _action_failures(case, actions or {})
    if case.required_skill and case.required_skill not in (skills_loaded or set()):
        failures.append(
            f"skill {case.required_skill!r} was not loaded ({sorted(skills_loaded or set()) or 'none'})"
        )
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


def case_timeout(case: EvalCase) -> float:
    """Seconds a case may run: a deep-research run outlasts a chat turn."""
    from src.config import Config

    if case.deep_research:
        return max(Config.EVAL_CASE_TIMEOUT_SECONDS, Config.DEEP_RESEARCH_RUN_TIMEOUT_SECONDS)
    return Config.EVAL_CASE_TIMEOUT_SECONDS


def run_with_timeout(fn: Callable[[], Any], timeout_s: float) -> Any:
    """Run `fn`, raising TimeoutError if it outlives `timeout_s`.

    Evals drive ChatAgent directly, and CHAT_TIMEOUT_SECONDS is enforced at the route
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


def chat_model() -> str:
    """The turn's chat model: --model (EVAL_CHAT_MODEL, inherited by workers)
    or DEFAULT_MODEL. Only the chat model moves; delegate, deep-research,
    side models and the judge stay as configured."""
    from src.config import Config

    return os.environ.get("EVAL_CHAT_MODEL") or Config.DEFAULT_MODEL


def check_model(model: str) -> str | None:
    """Why `model` cannot run the suite, or None. It must be priced, or its
    spend would be reported at another model's rates."""
    from src.config import Config

    if model in Config.MODEL_PRICING:
        return None
    return f"unknown model {model!r}: add its MODEL_PRICING entry (priced: {', '.join(sorted(Config.MODEL_PRICING))})"


@contextlib.contextmanager
def _gate_recorder() -> Iterator[list[Any]]:
    """Record the freshness gate's decisions during a turn (agent.py calls it
    through the module, so the wrapper sees every call)."""
    from unittest.mock import patch

    from src.agent import freshness

    decisions: list[Any] = []
    original = freshness.decide_freshness

    def recording(*args: Any, **kwargs: Any) -> Any:
        decision = original(*args, **kwargs)
        decisions.append(decision)
        return decision

    with patch.object(freshness, "decide_freshness", recording):
        yield decisions


def _gate_summary(decisions: list[Any]) -> dict[str, Any] | None:
    """The turn's gate verdict, or None where the gate did not run (standing chats)."""
    if not decisions or decisions[-1] is None:
        return None
    last = decisions[-1]
    return {"thinking": last.thinking, "lookup": bool(last.lookup)}


def _cost_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate spend over the cases that actually ran."""
    from src.config import Config

    ran = [r for r in results if not r.get("skipped")]
    # A timed-out or crashed case spent tokens the harness never saw
    unpriced = [r["id"] for r in ran if r.get("cost_usd") is None]

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
        "live_web_usd": round(
            sum(float(r.get("cost_usd") or 0) for r in ran if r.get("web") == "live"), 6
        ),
        "cases_priced": len(ran) - len(unpriced),
        "unpriced_cases": unpriced,
        "agent_model": chat_model(),
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


def _attachment_payload(case: EvalCase) -> list[dict[str, str]]:
    """Attachment fixtures -> the same shape the API layer hands to ChatAgent."""
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
    return files_payload


def _seed_case(
    case: EvalCase, user: Any, db: Any, conversation_id: str
) -> tuple[list[str], list[dict[str, Any]] | None, dict[str, float]]:
    """Seed the case's memories, past conversation and artifacts.

    Returns the seeded memory ids (for cleanup), the history the turn sees,
    and the compaction summarizer's estimated token usage.
    """

    # Seed memories (soft-deleted afterwards so they don't leak into later cases)
    seeded_memory_ids = [
        db.add_memory(user.id, m["content"], m.get("category") or "fact").id for m in case.memories
    ]
    # A condensed memory (its summary is what the per-turn list shows)
    for memory_id, m in zip(seeded_memory_ids, case.memories, strict=True):
        if m.get("summary"):
            db.set_memory_summary(memory_id, m["content"], m["summary"])

    # Seed a past conversation for episodic-recall cases
    if case.seed_conversation:
        past = db.create_conversation(
            user.id,
            str(case.seed_conversation.get("title", "Past chat")),
            model=chat_model(),
        )
        for msg in case.seed_conversation.get("messages", []):
            db.add_message(past.id, str(msg["role"]), str(msg["content"]))

    for entry in case.kv:
        key = entry["key"].replace("{conversation_id}", conversation_id)
        db.kv_set(user.id, entry["namespace"], key, entry["value"])
    _seed_proposals(case, user, db, conversation_id)

    # Seed artifacts for revision cases (they go with the eval conversation)
    artifact_ids = []
    for a in case.artifacts:
        artifact = db.create_artifact(conversation_id, user.id, str(a["title"]), str(a["html"]))[0]
        if a.get("state") is not None:
            db.set_artifact_state(artifact.id, a["state"])
        artifact_ids.append(artifact.id)
    history, summarizer_usage = _seeded_history(case, user, db, conversation_id, artifact_ids)
    return seeded_memory_ids, history, summarizer_usage


def _seeded_history(
    case: EvalCase, user: Any, db: Any, conversation_id: str, artifact_ids: list[str]
) -> tuple[list[dict[str, Any]] | None, dict[str, float]]:
    """The history the turn sees (files stored, compacted or behind a frozen
    summary) and the compaction summarizer's estimated token usage."""
    if case.compact_history:
        return _compacted_history(case, user, db, conversation_id)
    if case.frozen_summary:
        # A program chat already stored its user turns (_program_conversation)
        frozen = seed_frozen_summary(
            case,
            user,
            db,
            conversation_id,
            store_messages=case.mode not in _CANNED_PROGRAMS,
            history=with_artifact_ids(case.history, artifact_ids),
            summary=with_artifact_ids([{"text": case.frozen_summary}], artifact_ids)[0]["text"],
        )
        return frozen, {"input": 0.0, "output": 0.0}
    history = with_artifact_ids(case.history, artifact_ids) or None
    if history and any(turn.get("files") for turn in history):
        history = _history_with_files(history, db, conversation_id)
    return history, {"input": 0.0, "output": 0.0}


def _seed_proposals(case: EvalCase, user: Any, db: Any, conversation_id: str) -> None:
    """The case's pending cards, shown under the history's last reply."""
    if not case.proposals:
        return
    import uuid

    from src.db.models import Proposal
    from src.utils.clock import utc_now

    last: dict[str, Any] = next(
        (h for h in reversed(case.history) if h.get("role") == "assistant"), {}
    )
    reply = db.add_message(conversation_id, "assistant", str(last.get("content", "")))
    for p in case.proposals:
        db.create_proposal(
            Proposal(
                id=str(uuid.uuid4()),
                user_id=user.id,
                conversation_id=conversation_id,
                message_id=reply.id,
                request_id="eval-seed",
                kind=str(p["kind"]),
                summary=str(p["summary"]),
                details=dict(p.get("details") or {}),
                options=[
                    {"label": str(p["label"]), "description": "", "payload": dict(p["payload"])}
                ],
                state="pending",
                chosen=None,
                result=None,
                resolved_by=None,
                reported=False,
                created_at=utc_now(),
                resolved_at=None,
            )
        )


def _turn_text(case: EvalCase, conversation_id: str) -> str:
    """The user's message as the agent gets it: a typed answer to the seeded
    cards is resolved first and the outcome follows as guidance (chat_turn)."""
    from src.agent.guidance import with_guidance
    from src.agent.proposals import answer_and_note

    note = answer_and_note(conversation_id, case.user) if case.proposals else None
    return with_guidance(case.user, [note])


def _history_with_files(
    history: list[dict[str, Any]], db: Any, conversation_id: str
) -> list[dict[str, Any]]:
    """Store a history whose turns carry files, as the app stores uploads.

    Each turn becomes a message of the eval conversation; its fixture files go
    to the blob store under that message, and the history the turn sees is
    built by enrich_history - so the files are listed (message_id, file_index)
    exactly as in production and the tools can load them.
    """
    import base64
    import mimetypes

    from src.agent.history import enrich_history
    from src.db.models.helpers import save_file_to_blob_store
    from src.utils.files import UploadedFile

    messages = []
    for turn in history:
        files: list[UploadedFile] = []
        for rel_path in turn.get("files") or []:
            fixture = Path(__file__).parent / rel_path
            files.append(
                UploadedFile(
                    name=fixture.name,
                    type=mimetypes.guess_type(fixture.name)[0] or "application/octet-stream",
                    data=base64.b64encode(fixture.read_bytes()).decode(),
                )
            )
        message = db.add_message(
            conversation_id, turn["role"], turn["content"], files=files or None
        )
        for index, file in enumerate(files):
            save_file_to_blob_store(message.id, index, file)
        messages.append(message)
    return enrich_history(messages)


def _saved_attachments(case: EvalCase, db: Any, conversation_id: str) -> list[Any]:
    """The current turn's files, saved with their message as production does.

    The app saves the user message before the agent runs and gives each upload
    its history id (message_id:file_index), which execute_code(files=...)
    takes; sent unsaved, a current-turn file could not reach the sandbox.
    """
    from src.agent.message_content import annotate_history_file_ids
    from src.db.models.helpers import save_file_to_blob_store
    from src.utils.files import UploadedFile

    payload = [
        UploadedFile(name=f["name"], type=f["type"], data=f["data"])
        for f in _attachment_payload(case)
    ]
    if not payload:
        return []
    message = db.add_message(conversation_id, "user", case.user, files=payload)
    for index, file in enumerate(payload):
        save_file_to_blob_store(message.id, index, file)
    annotate_history_file_ids(message.id, payload)
    return payload


_CANNED_PROGRAMS = {"sports": ("Cyklistika", "cycling"), "language": ("Italština", "italian")}


# Agent mode: a real agent chat (create_standing_chat: the chat + its job),
# its context loaded the way production loads it
_CANNED_AGENT = (
    "Garden helper",
    "Each morning check the weather and tell the user whether the garden needs watering.",
    "0 7 * * *",
)


def program_identity(case: EvalCase) -> tuple[str, str]:
    """(name, id) of the program a sports/language case runs as."""
    name, program_id = _CANNED_PROGRAMS[case.mode]
    return case.program.get("name", name), case.program.get("id", program_id)


def _program_conversation(case: EvalCase, user: Any, db: Any) -> Any:
    """A real program chat with its program and stored data, as production has
    them: tools that resolve the chat's program (propose_setup_change) work."""
    import json

    name, program_id = program_identity(case)
    program = {"id": program_id, "name": name, "emoji": "🏁", "created_at": "2026-11-01"}
    db.kv_set(user.id, case.mode, "programs", json.dumps([program]))
    for key, value in case.program_kv.items():
        db.kv_set(user.id, case.mode, key, value)
    conversation = db.get_or_create_program_conversation(case.mode, user.id, program_id)
    # The history's user turns as messages (dated now): setup-change evidence
    # must cite a day the user really wrote in the chat
    for turn in case.history:
        if turn.get("role") == "user":
            db.add_message(conversation.id, "user", str(turn.get("content", "")))
    return conversation


def _save_user_turns(case: EvalCase, db: Any, conversation_id: str) -> None:
    """The history's user turns and the case's message as chat messages (dated now)."""
    for turn in case.history:
        if turn.get("role") == "user":
            db.add_message(conversation_id, "user", str(turn.get("content", "")))
    db.add_message(conversation_id, "user", case.user)


def _agent_conversation(user: Any, db: Any) -> Any:
    name, instructions, schedule = _CANNED_AGENT
    agent = db.create_standing_chat(user.id, name, instructions, schedule=schedule)
    return db.get_conversation(agent.conversation_id, user.id)


def _standing(case: EvalCase, conversation: Any = None, user: Any = None) -> Any:
    """Sports / language / agent mode: the standing chat's context, built the
    way production builds it (load_standing_context / standing_for_program)."""
    if case.mode == "agent":
        from src.agent.standing_context import load_standing_context

        return load_standing_context(conversation, user)
    if case.mode not in _CANNED_PROGRAMS:
        return None
    from src.agent.standing_context import standing_for_program

    name, program_id = program_identity(case)
    context = {"program_name": name, "program_id": program_id, "kv_data": dict(case.program_kv)}
    return standing_for_program(case.mode, context)  # type: ignore[arg-type]


def _run_turn(
    case: EvalCase,
    user: Any,
    conversation_id: str,
    request_id: str,
    history: list[dict[str, Any]] | None,
    standing: Any,
) -> tuple[str, list[dict[str, Any]], dict[str, Any], list[Any], dict[str, list[str]]]:
    """The agent turn: (response, tool_results, usage, result_messages, integration changes)."""
    from src.config import Config

    if case.memory_review:
        return _memory_review_turn(case, user, conversation_id, history)
    facts = _case_facts(case)
    # The flag binds the facts tool when the agent is built; restored after.
    # Switched on for the whole run, every case gets the (empty) facts block
    # an ordinary chat would - the rollout cost/latency check
    facts_were_enabled = Config.CONVERSATION_FACTS_ENABLED
    if facts is None and facts_were_enabled:
        facts = []
    Config.CONVERSATION_FACTS_ENABLED = facts is not None
    try:
        if case.round_cap is None:
            return _agent_turn(case, user, conversation_id, request_id, history, standing, facts)
        from src.agent.round_cap import round_cap_override

        with round_cap_override(case.round_cap):
            return _agent_turn(case, user, conversation_id, request_id, history, standing, facts)
    finally:
        Config.CONVERSATION_FACTS_ENABLED = facts_were_enabled


def _memory_review_turn(
    case: EvalCase, user: Any, conversation_id: str, history: list[dict[str, Any]] | None
) -> tuple[str, list[dict[str, Any]], dict[str, Any], list[Any], dict[str, list[str]]]:
    """Run the background memory review over the case's chat (no agent turn).

    The ops it applied come back as one manage_memory tool call, so the usual
    required/forbidden tool and argument checks grade it.
    """
    from langchain_core.messages import AIMessage

    from src.agent import memory_review
    from src.config import Config
    from src.db import models

    db = models.db
    for turn in history or []:
        db.add_message(conversation_id, str(turn["role"]), str(turn["content"]))
    db.add_message(conversation_id, "user", case.user)
    # The case runs as its own user (_case_user): nothing to clean up after
    result = memory_review.review_messages(
        user.id, conversation_id, db.get_messages(conversation_id)
    )
    calls = [{"name": "manage_memory", "args": {"operations": result.ops}, "id": "review"}]
    saved = memory_review.format_note(result.applied)
    response = f"Memory updated: {saved}" if result.ops else "Memory review: nothing saved."
    usage = {
        "answer_model": Config.AI_ASSIST_MODEL,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }
    message = AIMessage(content=response, tool_calls=calls if result.ops else [])
    return response, [], usage, [message], {}


def _case_facts(case: EvalCase) -> list[Any] | None:
    """The case's seeded facts as the turn's conversation_facts (None: feature off)."""
    if case.conversation_facts is None:
        return None
    from src.db.models import ConversationFact
    from src.utils.clock import utc_now

    return [
        ConversationFact(f["key"], f["text"], "eval-seed", utc_now())
        for f in case.conversation_facts
    ]


def _agent_turn(
    case: EvalCase,
    user: Any,
    conversation_id: str,
    request_id: str,
    history: list[dict[str, Any]] | None,
    standing: Any,
    facts: list[Any] | None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any], list[Any], dict[str, list[str]]]:
    """_run_turn's agent call, with the case's facts flag already set."""
    from evals.fakes import fake_integrations, recorded_actions
    from src.agent.agent import ChatAgent
    from src.db.models import db

    agent = ChatAgent(model_name=chat_model(), standing=standing)
    # Fake integration backends replace only the HTTP/client seams, so
    # the real tool code runs (no-op when the case declares none)
    with fake_integrations(case.integrations, web=case.web) as fakes:
        # tool_results is needed for pricing: image generations and
        # delegate_task subagent tokens are only visible in there.
        if case.deep_research:
            response, tool_results, usage, result_messages = run_deep_research_turn(
                case.deep_research, request_id
            )
        else:
            response, tool_results, usage, result_messages = agent.chat_batch(
                text=_turn_text(case, conversation_id),
                files=_saved_attachments(case, db, conversation_id) or None,
                history=history,
                user_name="Eval User",
                user_id=user.id,
                conversation_id=conversation_id,
                conversation_facts=facts,
            )
        if fakes.get("web") is not None:
            usage["eval_web"] = fakes["web"].summary()
        return response, tool_results, usage, result_messages, recorded_actions(fakes)


_SEARCH_TOOLS = frozenset({"web_search", "research"})


def _search_failed(content: str) -> bool:
    """A web_search/research result in which every search failed (no results
    found is a real outcome, not a failure)."""
    if "All searches failed" in content:
        return True
    try:
        parsed = json.loads(content)
    except ValueError:
        return False
    items = parsed if isinstance(parsed, list) else [parsed]
    return bool(items) and all(
        isinstance(i, dict) and "error" in i and not i.get("results") for i in items
    )


def search_outage(result_messages: list[Any]) -> bool:
    """Every search the turn made failed - the provider, not the agent (the
    laptop's ddgs throttles after many evals)."""
    from langchain_core.messages import ToolMessage

    searches = [
        str(m.content)
        for m in result_messages
        if isinstance(m, ToolMessage) and m.name in _SEARCH_TOOLS
    ]
    return bool(searches) and all(_search_failed(c) for c in searches)


def _tools_used(result_messages: list[Any]) -> set[str]:
    """Tools the turn executed, plus every tool call it requested."""
    from langchain_core.messages import ToolMessage

    tools_used = {msg.name for msg in result_messages if isinstance(msg, ToolMessage) and msg.name}
    # set_conversation_title may be extract-only (never executed):
    # count requested tool calls too so required_tools can reference them
    for msg in result_messages:
        for tool_call in getattr(msg, "tool_calls", None) or []:
            if tool_call.get("name"):
                tools_used.add(tool_call["name"])
    return tools_used


def _judge(
    case: EvalCase,
    response: str,
    usage: dict[str, Any],
    result_messages: list[Any],
    tools_used: set[str],
    integration_changes: str,
) -> tuple[int, bool, str, int, int]:
    """Grade the response: (score, pass, reasoning, judge input tokens, judge output tokens)."""
    from langchain_core.messages import HumanMessage
    from langchain_google_genai import ChatGoogleGenerativeAI

    from src.agent.content import extract_read_sources, extract_text_content
    from src.config import Config

    judge = ChatGoogleGenerativeAI(
        model=Config.EVAL_JUDGE_MODEL, google_api_key=Config.GEMINI_API_KEY, temperature=0.0
    )
    # A deep-research report cites the run's merged pages
    cited = usage.get("research_sources") or extract_read_sources(result_messages)
    judge_reply = judge.invoke(
        [
            HumanMessage(
                content=_JUDGE_INSTRUCTION.format(
                    rubric=case.rubric,
                    user=case.user,
                    response=annotate_for_judge(response, usage.get("grounding"))[
                        :JUDGE_RESPONSE_MAX_CHARS
                    ],
                    tools_called=", ".join(sorted(tools_used)) or "none",
                    cited_sources=json.dumps(cited, ensure_ascii=False) if cited else "none",
                    integration_changes=integration_changes,
                )
            )
        ]
    )
    score, judge_pass, reasoning = parse_judge_response(extract_text_content(judge_reply.content))
    return score, judge_pass, reasoning, *_judge_tokens(judge_reply)


def _case_user(case: EvalCase, user: Any, db: Any) -> Any:
    """The user a case runs as. Cases share one user and run in parallel; a
    memory-review case gets a fresh one, since the review reads the whole
    bank and the recently deleted memories (cleanups read as "removed by the
    user - do not re-add"); an agent-mode case too (agent names are unique
    per user)."""
    if not (case.memory_review or case.mode == "agent"):
        return user
    import uuid

    return db.get_or_create_user(f"eval-{case.id}-{uuid.uuid4().hex[:8]}@example.com", "Eval User")


def _run_case(case: EvalCase, user: Any, db: Any) -> dict[str, Any]:
    """Execute one case through ChatAgent and judge it."""
    import uuid

    from src.agent.tool_results import set_current_request_id
    from src.agent.tools import set_standing_namespace
    from src.agent.tools.context import set_conversation_context
    from src.agent.tools.turn_usage import reset_turn_usage
    from src.config import Config
    from src.services.costs import calculate_token_cost

    user = _case_user(case, user, db)
    if case.mode == "agent":
        conversation = _agent_conversation(user, db)
    elif case.mode in _CANNED_PROGRAMS:
        conversation = _program_conversation(case, user, db)
    else:
        conversation = db.create_conversation(user.id, f"eval-{case.id}", model=chat_model())
        if case.save_user_turns:
            _save_user_turns(case, db, conversation.id)
    set_conversation_context(conversation.id, user.id)
    # Per-turn tool bookkeeping (batching nudges, web_search -> research
    # upgrade) is keyed by request id; without one it is inert, so evals
    # used to measure round counts with every efficiency mechanism off
    request_id = f"eval-{case.id}-{uuid.uuid4().hex[:8]}"
    set_current_request_id(request_id)

    seeded_memory_ids, history, summarizer_usage = _seed_case(case, user, db, conversation.id)
    standing = _standing(case, conversation, user)
    if standing is not None:
        set_standing_namespace(standing.kv_namespace)
    try:
        turn_started = time.monotonic()
        with _gate_recorder() as gate_decisions:
            response, tool_results, usage, result_messages, actions = _run_turn(
                case, user, conversation.id, request_id, history, standing
            )
    finally:
        set_conversation_context(None, None)
        reset_turn_usage()
        set_current_request_id(None)
        if standing is not None:
            set_standing_namespace(None)
        for memory_id in seeded_memory_ids:
            db.delete_memory(memory_id, user.id)

    tools_used = _tools_used(result_messages)
    tool_rounds = int(usage.get("tool_rounds", 0))
    failures = deterministic_failures(
        case,
        tools_used,
        tool_rounds,
        skills_loaded=skills_loaded_in(result_messages),
        tool_calls=tool_calls_in(result_messages),
        actions=actions,
    )
    score, judge_pass, reasoning, judge_input, judge_output = _judge(
        case, response, usage, result_messages, tools_used, describe_recorded(actions)
    )

    # The judge is a real billed API call - roughly a third of a run's spend,
    # since it re-sends the rubric plus the full response on a Pro model. It
    # went unmeasured before, so "a few cents per run" was a guess.
    judge_cost = calculate_token_cost(Config.EVAL_JUDGE_MODEL, judge_input, judge_output)
    agent_cost = turn_cost(chat_model(), usage, tool_results)
    # Compaction cases also pay for building the summary (estimated tokens)
    agent_cost += calculate_token_cost(
        Config.AI_ASSIST_MODEL, int(summarizer_usage["input"]), int(summarizer_usage["output"])
    )

    passed = judge_pass and not failures
    # A live case that failed while every search it made failed: infrastructure
    infra = (
        "live search failed"
        if not passed and case.web == "live" and search_outage(result_messages)
        else None
    )
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
        "history_from": case.history_from,
        "web": "live" if case.web == "live" else "canned",
        "web_calls": usage.get("eval_web"),
        **({"infra": infra} if infra else {}),
        "model": chat_model(),
        "gate": _gate_summary(gate_decisions),
        "judge_reasoning": reasoning,
        "response_preview": response[:200],
        "grounding": grounding_summary(usage),
    }


# Metered search providers' keys, blanked for evals so the chain falls through
# to the unmetered ddgs fallback. The local .env holds the same keys as prod,
# and eval usage is counted only in the throwaway DB - so eval searches spent
# the family's real monthly quota while prod's counters never saw them.
EVAL_BLANKED_SEARCH_KEYS = (
    "BRAVE_SEARCH_API_KEY",
    "TAVILY_API_KEY",
    "EXA_API_KEY",
    "LINKUP_API_KEY",
)


def isolate_environment() -> None:
    """Isolated temp DB and blob store + prod Gemini key + ddgs-only web search, BEFORE
    importing src.* (Config reads env at import). Each process migrates its database (evals/pool.py). Called by the
    main process and by every worker, so each owns its own database."""
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")
    db_dir = tempfile.mkdtemp(prefix="evals-")
    os.environ["DATABASE_PATH"] = str(Path(db_dir) / "eval.db")
    # Attachments and generated files too: never the repo's dev files.db
    os.environ["BLOB_STORAGE_PATH"] = str(Path(db_dir) / "files.db")
    os.environ["EMBEDDINGS_ENABLED"] = "false"  # keep eval runs cheap and focused
    for key in EVAL_BLANKED_SEARCH_KEYS:
        os.environ[key] = ""


def execute_case(case: EvalCase, user: Any, db: Any) -> dict[str, Any]:
    """Run one case under the per-case timeout; never raises."""
    if case.requires and not _requirements_met(case):
        return {"id": case.id, "skipped": True}
    print(f"RUN   {case.id} ...", flush=True)
    try:
        result: dict[str, Any] = run_with_timeout(
            lambda: _run_case(case, user, db), case_timeout(case)
        )
    except TimeoutError as e:
        # Abandoned, not retried: the worker thread is stuck in a socket
        # read we cannot interrupt, so the suite moves on without it.
        result = {"id": case.id, "pass": False, "score": 0, "error": str(e), "timed_out": True}
    except Exception as e:  # noqa: BLE001 - a crashed case is a failed case, not a dead run
        result = {"id": case.id, "pass": False, "score": 0, "error": str(e)}
    if case.known_failure:
        result["known_failure"] = case.known_failure
    return result


def _status(result: dict[str, Any]) -> str:
    """PASS, FAIL, or TARGET for a failing case marked known_failure."""
    if result.get("pass"):
        return "PASS"
    if result.get("infra"):
        return "INFRA"
    return "TARGET" if result.get("known_failure") else "FAIL"


def _print_result(result: dict[str, Any]) -> None:
    if result.get("skipped"):
        print(f"SKIP  {result['id']} (requirements not met)", flush=True)
        return
    status = _status(result)
    cost = result.get("cost_usd")
    cost_str = f" cost={_usd(cost)}" if cost is not None else ""
    print(
        f"{status}  {result['id']} score={result.get('score')} "
        f"rounds={result.get('tool_rounds')} t={result.get('duration_s')}s{cost_str}",
        flush=True,
    )


def _print_summary(
    results: list[dict[str, Any]], cost: dict[str, Any], elapsed: float, workers: int
) -> None:
    """Pass counts, spend, and why each failing case failed."""
    ran = [r for r in results if not r.get("skipped")]
    passed = sum(1 for r in ran if r.get("pass"))
    targets = [r for r in ran if _status(r) == "TARGET"]
    infra = [r for r in ran if _status(r) == "INFRA"]
    print(
        f"\n{passed}/{len(ran)} passed ({len(results) - len(ran)} skipped"
        + (f", {len(targets)} known targets failing" if targets else "")
        + (f", {len(infra)} infra - not the agent" if infra else "")
        + f") in {elapsed / 60:.1f} min on {workers} workers"
    )
    gaps: dict[str, list[str]] = {
        r["id"]: list((r.get("web_calls") or {}).get("missing") or []) for r in ran
    }
    gaps = {k: v for k, v in gaps.items() if v}
    if gaps:
        print("  Canned pages missing (recapture? evals/capture_web.py):")
        for case_id, urls in gaps.items():
            print(f"    {case_id}: {', '.join(urls[:3])}" + (" ..." if len(urls) > 3 else ""))

    print(f"\nCost: {_usd(cost['total_usd'])} total for {cost['cases_priced']} priced cases")
    if cost.get("live_web_usd"):
        print(f"  live-web cases: {_usd(cost['live_web_usd'])} of it")
    if cost["unpriced_cases"]:
        print(
            "  NOT PRICED (timed out or crashed - real spend unknown): "
            + ", ".join(cost["unpriced_cases"])
        )
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

    for r in ran:
        if not r.get("pass"):
            reason = "; ".join(r.get("deterministic_failures", [])) or r.get(
                "judge_reasoning", r.get("error", "")
            )
            print(f"  {_status(r)} {r['id']}: {reason}")
        elif r.get("known_failure"):
            print(f"  TARGET PASSED {r['id']}: drop its known_failure if it keeps passing")


def _run_once(
    cases: list[EvalCase],
    workers: int,
    index: int,
    earlier: list[dict[str, Any]],
    out_path: Path,
) -> list[dict[str, Any]]:
    """One pass over the cases (repeat `index`), in case order."""
    from evals.pool import run_cases

    done: dict[str, dict[str, Any]] = {}

    def on_result(result: dict[str, Any]) -> None:
        result["repeat"] = index
        done[result["id"]] = result
        # Flush after every case so a hang or Ctrl-C keeps what was paid for
        write_results(out_path, earlier + in_case_order(cases, done))
        _print_result(result)

    run_cases(cases, workers, on_result)
    return in_case_order(cases, done)


def _run_repeats(
    cases: list[EvalCase], workers: int, repeat: int, out_path: Path
) -> list[dict[str, Any]]:
    """Every repeat's results in case order, each tagged with its repeat index."""
    finished: list[dict[str, Any]] = []
    for index in range(repeat):
        finished += _run_once(cases, workers, index, finished, out_path)
    return finished


def _print_repeats(results: list[dict[str, Any]], repeat: int) -> None:
    """Per case k/N over the repeats, and the pass rate on gate-low cases."""
    ran = [r for r in results if not r.get("skipped")]
    if repeat > 1:
        for case_id, (passes, runs, score, _) in _per_case(ran, repeat).items():
            if passes < runs:
                print(f"  {case_id}: {passes}/{runs} passed, mean score {score}")
    low = [r for r in ran if _gate_thinking(r) == "low"]
    if low:
        passed = sum(1 for r in low if r.get("pass"))
        print(f"  gate-low runs: {passed}/{len(low)} passed")


HISTORY_PATH = Path(__file__).parent / "history.jsonl"


def _git_sha() -> str:
    """The checkout's short sha, "-dirty" when it has uncommitted changes."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 - git from PATH
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],  # noqa: S607 - git from PATH
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except OSError, subprocess.CalledProcessError:
        return "unknown"
    return f"{sha}-dirty" if dirty else sha


def _gate_thinking(result: dict[str, Any]) -> str | None:
    gate = result.get("gate") or {}
    return gate.get("thinking")


def _per_case(ran: list[dict[str, Any]], repeat: int) -> dict[str, list[Any]]:
    """[pass, score, gate] per case; with repeats [passes, runs, mean score, gate]."""
    if repeat <= 1:
        return {r["id"]: [bool(r.get("pass")), r.get("score"), _gate_thinking(r)] for r in ran}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in ran:
        grouped.setdefault(r["id"], []).append(r)
    return {
        case_id: [
            sum(bool(r.get("pass")) for r in runs),
            len(runs),
            round(sum(float(r.get("score") or 0) for r in runs) / len(runs), 2),
            _gate_thinking(runs[-1]),
        ]
        for case_id, runs in grouped.items()
    }


def history_line(
    results: list[dict[str, Any]],
    cost: dict[str, Any],
    selection: str,
    elapsed: float,
    repeat: int = 1,
) -> dict[str, Any]:
    """One run in the tracked log: what ran, on what, how it went and what it cost.

    Per case [pass, score, gate thinking] ([passes, runs, mean score, gate]
    with --repeat); TARGET cases also show as false - known_failing lists
    them so a reader can tell new failures from the known ones. With repeats,
    passed/ran count runs, not cases (the repeat field says how many). web counts
    canned vs live cases, so runs before canned web are not compared as equals.
    """
    ran = [r for r in results if not r.get("skipped")]
    first = {r["id"]: r for r in reversed(ran)}  # one result per case
    return {
        "at": to_local(utc_now()).strftime("%Y-%m-%d %H:%M"),
        "sha": _git_sha(),
        "agent_model": cost["agent_model"],
        "judge_model": cost["judge_model"],
        "selection": selection,
        "repeat": repeat,
        "passed": sum(1 for r in ran if r.get("pass")),
        "ran": len(ran),
        "known_failing": sorted({r["id"] for r in ran if _status(r) == "TARGET"}),
        "cost_usd": round(float(cost["total_usd"]), 4),
        "live_web_usd": round(float(cost.get("live_web_usd") or 0), 4),
        "minutes": round(elapsed / 60, 1),
        "web": {
            "canned": sum(1 for r in first.values() if r.get("web") != "live"),
            "live": sum(1 for r in first.values() if r.get("web") == "live"),
        },
        "gate_low": sum(1 for r in first.values() if _gate_thinking(r) == "low"),
        # Failures that say nothing about the agent, and canned captures with gaps
        "infra": sorted({r["id"] for r in ran if r.get("infra")}),
        "canned_missing": {
            r["id"]: len((r.get("web_calls") or {}).get("missing") or [])
            for r in first.values()
            if (r.get("web_calls") or {}).get("missing")
        },
        "cases": _per_case(ran, repeat),
    }


def append_history(path: Path, line: dict[str, Any]) -> None:
    """Append one run to the tracked results log (evals/results/ is gitignored)."""
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default=str(Path(__file__).parent / "cases"))
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="case ids or globs (quote them), comma-separated or repeated",
    )
    parser.add_argument("--workers", type=int, help="parallel cases (default EVAL_WORKERS)")
    parser.add_argument(
        "--smoke", action="store_true", help="only the ~$1 smoke subset (cases with smoke: true)"
    )
    parser.add_argument(
        "--model",
        help="chat model for the turns (default DEFAULT_MODEL); judge and side models stay",
    )
    parser.add_argument("--repeat", type=int, default=1, help="run the selection N times")
    args = parser.parse_args()

    isolate_environment()
    if args.model:
        # Read by chat_model() here and in the workers (they inherit the env)
        os.environ["EVAL_CHAT_MODEL"] = args.model
    # Imported here, not at module scope: Config reads env at import time and
    # must not be loaded before the DATABASE_PATH override above.
    from src.config import Config

    if error := check_model(chat_model()):
        print(error)
        return 1
    try:
        cases = select_cases(load_cases(Path(args.cases)), args.only)
    except ValueError as e:
        print(e)
        return 1
    if args.smoke:
        cases = [c for c in cases if c.smoke]
    selection = "smoke" if args.smoke else ",".join(args.only) or "all"
    workers = max(1, args.workers or Config.EVAL_WORKERS)

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    out_path = results_dir / f"{to_local(utc_now()).strftime('%Y%m%d-%H%M%S')}.json"
    repeat = max(1, args.repeat)
    print(
        f"{len(cases)} cases x{repeat} on {min(workers, len(cases))} workers, model {chat_model()}",
        flush=True,
    )
    started = time.monotonic()
    results = _run_repeats(cases, workers, repeat, out_path)
    elapsed = time.monotonic() - started

    cost = _cost_summary(results)
    write_results(out_path, results)
    append_history(HISTORY_PATH, history_line(results, cost, selection, elapsed, repeat))
    _print_summary(results, cost, elapsed, min(workers, len(cases)))
    _print_repeats(results, repeat)
    print(f"\nResults: {out_path} (one line appended to {HISTORY_PATH.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
