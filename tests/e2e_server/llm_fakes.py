"""Gemini fakes: the chat model, the token streams and the grounding check."""

import time
from typing import Any
from unittest.mock import MagicMock

from tests.e2e_server.context import MOCK_CONFIG

# Release-gated thinking (thinking_until_released): flush re-send, poll, cap
THINKING_RESEND_DELAY_SECONDS = 0.3
THINKING_RELEASE_POLL_SECONDS = 0.05
THINKING_RELEASE_MAX_SECONDS = 25


def create_mock_llm() -> MagicMock:
    """Create mock LLM that returns proper AIMessage objects.

    The mock returns a proper AIMessage object that LangGraph can process,
    rather than a MagicMock which causes "Unsupported message type" errors.
    """
    from langchain_core.messages import AIMessage

    mock = MagicMock()
    mock_instance = MagicMock()

    def mock_invoke(messages: list[Any], **kwargs: Any) -> AIMessage:
        # Apply batch delay if configured (for testing conversation switching)
        batch_delay_ms = MOCK_CONFIG.get("batch_delay_ms", 0)
        if batch_delay_ms > 0:
            time.sleep(batch_delay_ms / 1000)

        # Extract user message from the last message
        user_message = ""
        if messages:
            last_msg = messages[-1]
            if hasattr(last_msg, "content"):
                content = last_msg.content
                if isinstance(content, str):
                    user_message = content
                elif isinstance(content, list):
                    # Extract text from multimodal content
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            user_message = part.get("text", "")
                            break

        # Use custom response if set, otherwise use prefix + message
        if MOCK_CONFIG["custom_response"]:
            response_text = MOCK_CONFIG["custom_response"]
        else:
            prefix = MOCK_CONFIG["response_prefix"]
            response_text = f"{prefix}{user_message[:100]}"

        # Return a proper AIMessage that LangGraph can process
        input_tokens = MOCK_CONFIG["input_tokens"]
        output_tokens = MOCK_CONFIG["output_tokens"]
        return AIMessage(
            content=response_text,
            usage_metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )

    mock_instance.invoke = mock_invoke
    # Ensure bind_tools returns the same instance so tool binding works
    mock_instance.bind_tools = MagicMock(return_value=mock_instance)
    mock.return_value = mock_instance
    return mock


def _mock_artifact_turn(
    user_id: str | None, conversation_id: str | None
) -> tuple[dict[str, Any] | None, list[Any]]:
    """Run the real artifact tool for the canned artifact (one-shot): the
    `artifact` event and the turn's result messages, as the real stream has."""
    spec = MOCK_CONFIG.get("artifact_next")
    if not spec or not user_id or not conversation_id:
        return None, []
    MOCK_CONFIG["artifact_next"] = None
    from langchain_core.messages import AIMessage, ToolMessage

    from src.agent.artifact_refs import artifact_ref_from_tool_content
    from src.agent.tools.artifacts import create_artifact, update_artifact
    from src.agent.tools.context import set_conversation_context

    set_conversation_context(conversation_id, user_id)
    if spec.get("update"):
        name, args = (
            "update_artifact",
            {"artifact_id": MOCK_CONFIG.get("last_artifact_id"), "html": spec["html"]},
        )
        content = update_artifact.invoke(args)
    else:
        name, args = "create_artifact", {"title": spec["title"], "html": spec["html"]}
        content = create_artifact.invoke(args)
    ref = artifact_ref_from_tool_content(name, content)
    if ref:
        MOCK_CONFIG["last_artifact_id"] = ref["id"]
    call = {"name": name, "args": args, "id": "call-art"}
    messages = [
        AIMessage(content="", tool_calls=[call]),
        ToolMessage(name=name, content=content, tool_call_id="call-art"),
    ]
    return ({"type": "artifact", **ref} if ref else None), messages


def create_mock_stream_chat_events() -> Any:  # noqa: C901, PLR0915
    """Create a mock stream_chat_events method that yields structured events.

    This method yields events including thinking, tool_start, tool_end, token, and final.
    """
    from collections.abc import Generator

    def mock_stream_chat_events(  # noqa: C901, PLR0912, PLR0915
        self: Any,
        text: str,
        files: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        force_tools: list[str] | None = None,
        user_name: str | None = None,
        user_id: str | None = None,
        custom_instructions: str | None = None,
        is_planning: bool = False,
        dashboard_data: dict[str, Any] | None = None,
        conversation_id: str | None = None,
        is_autonomous: bool = False,
        agent_context: dict[str, Any] | None = None,
        is_sports: bool = False,
        sports_context: dict[str, Any] | None = None,
        is_language: bool = False,
        language_context: dict[str, Any] | None = None,
        conversation_title: str | None = None,
    ) -> Generator[dict[str, Any]]:
        """Mock streaming that yields structured events."""
        # Use custom response if set, otherwise use prefix + message
        if MOCK_CONFIG["custom_response"]:
            response_text = MOCK_CONFIG["custom_response"]
        else:
            prefix = MOCK_CONFIG["response_prefix"]
            response_text = f"{prefix}{text[:100]}"

        delay_s = MOCK_CONFIG["stream_delay_ms"] / 1000

        if MOCK_CONFIG.get("fail_next_stream"):
            MOCK_CONFIG["fail_next_stream"] = False
            raise RuntimeError("mock model failure")

        # Optionally simulate a transient model error being retried
        if MOCK_CONFIG.get("emit_retry_hold_ms"):
            yield {"type": "retry", "attempt": 1, "max_retries": 3}
            time.sleep(MOCK_CONFIG["emit_retry_hold_ms"] / 1000)

        # Optionally yield a thinking event (based on mock config or message content)
        if "think" in text.lower() or MOCK_CONFIG.get("emit_thinking"):
            time.sleep(delay_s)
            thinking_event = {"type": "thinking", "text": MOCK_CONFIG["thinking_text"]}
            yield thinking_event
            if MOCK_CONFIG["thinking_hold_ms"]:
                # WebKit (Linux CI) holds an SSE chunk until the next one
                # arrives: re-send the (accumulated, unchanged) thinking
                # halfway, so the page sees it while the hold still runs -
                # not together with the first answer token
                half_hold_s = MOCK_CONFIG["thinking_hold_ms"] / 2000
                time.sleep(half_hold_s)
                yield thinking_event
                time.sleep(half_hold_s)
            elif MOCK_CONFIG.get("thinking_until_released"):
                # Re-sent once to flush WebKit's held chunk (each re-send
                # re-renders the live line under the test's taps), then held
                # silently; capped so an unreleased test cannot wedge the thread
                from src.agent.cancellation import is_cancelled as _cancelled

                time.sleep(THINKING_RESEND_DELAY_SECONDS)
                yield thinking_event
                held_until = time.monotonic() + THINKING_RELEASE_MAX_SECONDS
                while not MOCK_CONFIG.get("thinking_released") and not _cancelled():
                    if time.monotonic() > held_until:
                        break
                    time.sleep(THINKING_RELEASE_POLL_SECONDS)

        # Optionally yield tool events (if force_tools specified)
        if force_tools:
            for tool in force_tools:
                time.sleep(delay_s)
                # Same display metadata the real stream attaches (stream_events.py)
                from src.agent.tool_display import TOOL_METADATA

                start: dict[str, Any] = {"type": "tool_start", "tool": tool}
                if tool in TOOL_METADATA:
                    start["metadata"] = TOOL_METADATA[tool]
                yield start
                time.sleep(delay_s * 2)  # Simulate tool execution
                yield {"type": "tool_end", "tool": tool}

        artifact_event, artifact_messages = _mock_artifact_turn(user_id, conversation_id)
        if artifact_event:
            yield artifact_event

        # Stream tokens word-by-word; honour server-side Stop like the real
        # stream_chat_events (checked per chunk, partial text is the reply)
        from src.agent.cancellation import STOP_REASON_USER, is_cancelled

        words = response_text.split()
        streamed = ""
        stop_reason = None
        for i, word in enumerate(words):
            if is_cancelled():
                stop_reason = STOP_REASON_USER
                break
            # Add space before word (except first)
            token = f" {word}" if i > 0 else word
            streamed += token
            yield {"type": "token", "text": token}
            time.sleep(delay_s)

        if MOCK_CONFIG.get("consume_steering") and user_id and conversation_id:
            from src.agent.interjection import pop_interjection

            pop_interjection(user_id, conversation_id)

        # Yield final event
        input_tokens = MOCK_CONFIG["input_tokens"]
        output_tokens = MOCK_CONFIG["output_tokens"]
        usage_info = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        final: dict[str, Any] = {
            "type": "final",
            "content": streamed if stop_reason else response_text,
            "metadata": {},
            "tool_results": [],
            "usage_info": usage_info,
        }
        if stop_reason:
            final["stop_reason"] = stop_reason
        if artifact_messages:
            final["result_messages"] = artifact_messages
        offer_args = MOCK_CONFIG.get("deep_research_offer")
        if offer_args:
            # The agent proposed deep research this turn (one-shot)
            from langchain_core.messages import AIMessage

            MOCK_CONFIG["deep_research_offer"] = None
            call = {"name": "propose_deep_research", "args": offer_args, "id": "call-dr"}
            final["result_messages"] = [AIMessage(content="", tool_calls=[call])]
        # Same post-answer step as ChatAgent.stream_chat_events (patched check below)
        from src.agent import grounding_check

        if grounding_check.should_check(final["content"], [], stop_reason):
            yield {"type": "grounding_started"}
        grounding_check.apply_grounding(final["content"], [], usage_info, stop_reason)
        yield final

    return mock_stream_chat_events


def mock_should_check(answer: str, result_messages: Any, stop_reason: str | None = None) -> bool:
    """The grounding check "runs" whenever a test set a canned result."""
    return bool(MOCK_CONFIG.get("grounding_result")) and not stop_reason


def mock_check_grounding(
    answer: str, result_messages: Any, stop_reason: str | None = None, history: Any = None
) -> Any:
    """The canned grounding outcome a test set via /test/set-grounding-result."""
    from src.agent.grounding_check import GroundingOutcome

    canned = MOCK_CONFIG.get("grounding_result") or {}
    if not canned or stop_reason:
        return GroundingOutcome()
    return GroundingOutcome(
        annotations=canned.get("annotations", []), summary=canned.get("summary"), usage=None
    )
