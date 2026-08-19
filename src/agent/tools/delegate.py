"""Delegate a research task to a scoped subagent (context isolation).

The subagent runs its own multi-round tool loop (research/web/fetch) in a
FRESH context: the 15k-char page dumps it reads never enter the main
conversation's history - only its final digest does. This is both a quality
lever (deep multi-page work without exhausting the main round cap) and a
cost lever (the main conversation re-bills its whole history every tool
round; the subagent's history starts empty).

The subagent's token usage rides in the tool result under _delegate_usage,
where the cost pipeline (calculate_and_save_message_cost) picks it up.
"""

import contextvars
import json
from typing import Any

from langchain_core.tools import tool

from src.agent.tools.permission_check import check_autonomous_permission
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

_in_delegate: contextvars.ContextVar[bool] = contextvars.ContextVar("_in_delegate", default=False)


@tool
def delegate_task(task: str, expected_output: str = "") -> str:
    """Delegate a self-contained research task to a focused subagent.

    Use for DEEP research (3+ sources, multi-step digging, comparisons that
    need verification) so the bulky intermediate pages stay out of this
    conversation. The subagent can search the web and read pages; it returns
    a digest with sources. Give it a complete, self-contained brief - it
    cannot see this conversation.

    Args:
        task: Complete description of what to find out. Include ALL relevant
            context (names, dates, constraints) - the subagent starts blank.
        expected_output: Optional description of the desired answer format.

    Returns:
        JSON: {result, sources: [{title, url}]}.
    """
    check_autonomous_permission("delegate_task", {"task": task[:200]})

    if _in_delegate.get():
        return json.dumps({"error": "Nested delegation is not allowed.", "retriable": False})
    if not task or not task.strip():
        return json.dumps({"error": "task must not be empty.", "retriable": False})

    # Imported here: delegate -> agent -> tools/__init__ -> delegate would be
    # a circular import at module load time
    from src.agent.agent import ChatAgent
    from src.agent.content import extract_cited_sources
    from src.agent.prompts import DELEGATE_SYSTEM_PROMPT
    from src.agent.tools import cite_sources, fetch_url, research, web_search

    prompt = task.strip()
    if expected_output.strip():
        prompt += f"\n\nExpected output: {expected_output.strip()}"

    logger.info(
        "delegate_task starting",
        extra={"task_preview": task[:120], "model": Config.DELEGATE_MODEL},
    )

    token = _in_delegate.set(True)
    try:
        subagent = ChatAgent(
            model_name=Config.DELEGATE_MODEL,
            with_tools=True,
            tools=[research, web_search, fetch_url, cite_sources],
            enable_context_cache=False,
            system_prompt_override=DELEGATE_SYSTEM_PROMPT,
        )
        response_text, _tool_results, usage_info, result_messages = subagent.chat_batch(text=prompt)
    except Exception as e:
        logger.error("delegate_task failed", extra={"error": str(e)}, exc_info=True)
        return json.dumps({"error": f"Delegated task failed: {e}"})
    finally:
        _in_delegate.reset(token)

    sources = extract_cited_sources(result_messages)
    logger.info(
        "delegate_task completed",
        extra={
            "result_length": len(response_text),
            "sources": len(sources),
            "input_tokens": usage_info.get("input_tokens", 0),
            "output_tokens": usage_info.get("output_tokens", 0),
            "tool_rounds": usage_info.get("tool_rounds", 0),
        },
    )

    payload: dict[str, Any] = {
        "result": response_text or "(subagent produced no text)",
        "sources": sources,
        # Consumed by the cost pipeline; kept at the top level so it survives
        # _full_result stripping and lands in the saved tool results
        "_delegate_usage": {
            "model": Config.DELEGATE_MODEL,
            "input_tokens": usage_info.get("input_tokens", 0),
            "output_tokens": usage_info.get("output_tokens", 0),
            "cached_input_tokens": usage_info.get("cached_input_tokens", 0),
            "tool_rounds": usage_info.get("tool_rounds", 0),
        },
    }
    return json.dumps(payload)
