"""Graph stream -> client output translation for ChatAgent's streaming turns.

StreamEventProcessor (ChatAgent.stream_chat_events) consumes the
(mode, payload) pairs of a LangGraph stream(stream_mode=["messages",
"custom"]) and yields the structured events the SSE layer forwards
(thinking, tool_start/tool_end, token, retry, final), while accumulating the
turn's response text, tool results, messages and token usage.
iter_token_stream (ChatAgent.stream_chat) is the plain-token variant.
"""

import time
from collections.abc import Generator, Iterable, Iterator
from typing import Any

from langchain_core.messages import AIMessageChunk, BaseMessage, ToolMessage

from src.agent.content import (
    clean_tool_call_json,
    extract_text_content,
    extract_thinking_and_text,
)
from src.agent.graph import CHAT_NODE_NAME
from src.agent.tool_display import TOOL_METADATA, extract_tool_detail
from src.agent.turn_usage import TokenTotals, build_usage_info
from src.utils.logging import get_logger

logger = get_logger(__name__)

_MSG_CONTEXT_MARKER = "<!-- MSG_CONTEXT:"
_END_MARKER = "-->"


def _partial_suffix(text: str, marker: str) -> str:
    """Longest proper prefix of marker that text ends with ("" if none)."""
    for i in range(len(marker) - 1, 0, -1):
        if text.endswith(marker[:i]):
            return marker[:i]
    return ""


class MsgContextFilter:
    """Strips echoed <!-- MSG_CONTEXT: ... --> blocks from streamed text.

    The model occasionally echoes the history metadata prefix. A block may
    span several chunks and either marker may be split across a chunk
    boundary, so a partial marker at a chunk's end is held back as carryover
    until the next chunk decides what it was.
    """

    def __init__(self) -> None:
        # Inside an echoed MSG_CONTEXT block (spans multiple chunks)
        self.in_msg_context = False
        # Carryover buffer for cross-chunk boundary marker detection
        self.carryover = ""

    def feed(self, text_content: str) -> str:
        """Return the displayable part of a chunk's text ("" for none)."""
        # Prepend any carryover from previous chunk for marker detection
        if self.carryover:
            text_content = self.carryover + text_content
            self.carryover = ""

        # Check if we're currently inside a MSG_CONTEXT block
        if self.in_msg_context:
            if _END_MARKER not in text_content:
                # Still inside MSG_CONTEXT block - check for partial end marker
                self.carryover = _partial_suffix(text_content, _END_MARKER)
                return ""
            # Block ended - extract content after it
            end_pos = text_content.find(_END_MARKER)
            text_content = text_content[end_pos + 3 :].lstrip()
            self.in_msg_context = False
            logger.info("MSG_CONTEXT block ended (multi-chunk)")
            if not text_content:
                return ""

        # Check if MSG_CONTEXT starts in this chunk
        if _MSG_CONTEXT_MARKER in text_content:
            return self._strip_block_start(text_content)

        # Check if MSG_CONTEXT marker might be split at chunk boundary
        partial = _partial_suffix(text_content, _MSG_CONTEXT_MARKER)
        if partial:
            self.carryover = partial
            text_content = text_content[: -len(partial)]
        return text_content

    def _strip_block_start(self, text_content: str) -> str:
        """Handle a chunk in which a MSG_CONTEXT block starts."""
        marker_pos = text_content.find(_MSG_CONTEXT_MARKER)
        # Check if block completes in this chunk
        end_pos = text_content.find(_END_MARKER, marker_pos)
        if end_pos != -1:
            # Complete block in one chunk - strip it
            before = text_content[:marker_pos]
            after = text_content[end_pos + 3 :]
            text_content = (before + after).strip()
            logger.info(
                "Stripped echoed MSG_CONTEXT from output",
                extra={"remaining_len": len(text_content)},
            )
            return text_content
        # Block starts but doesn't end - check for partial end marker
        self.carryover = _partial_suffix(text_content[marker_pos:], _END_MARKER)
        self.in_msg_context = True
        logger.info("MSG_CONTEXT block started (will span chunks)")
        return text_content[:marker_pos].rstrip()


class StreamEventProcessor:
    """Accumulates one streamed turn and yields its client events."""

    def __init__(self, messages: list[BaseMessage]) -> None:
        # Accumulate full response text
        self.full_response = ""
        # Capture tool results for server-side extraction
        self.tool_results: list[dict[str, Any]] = []
        # Collect all messages for metadata tool arg extraction
        self.all_messages: list[BaseMessage] = list(messages)
        self.totals = TokenTotals()
        self.chunk_count = 0
        # Track active tool calls by tool_call_id (NOT name: two parallel calls
        # to the same tool must emit separate tool_start/tool_end events)
        self.pending_tool_calls: set[str] = set()
        # Accumulate thinking text across chunks
        self.accumulated_thinking = ""
        # Track token yields for debugging
        self.token_yield_count = 0
        self.msg_context = MsgContextFilter()

    def process(self, mode: str, event: Any) -> Iterator[dict[str, Any]]:
        """Events for one (mode, payload) pair from the graph stream."""
        if mode == "custom":
            if isinstance(event, dict) and event.get("type") == "retry":
                yield {
                    "type": "retry",
                    "attempt": event.get("attempt"),
                    "max_retries": event.get("max_retries"),
                }
            return
        # Guard clause: a non-tuple event must not fall through to the
        # processing below with an unbound/stale message_chunk
        if not (isinstance(event, tuple) and len(event) >= 1):
            return
        message_chunk = event[0]
        event_meta = event[1] if len(event) >= 2 and isinstance(event[1], dict) else {}
        source_node = event_meta.get("langgraph_node", "")

        # Capture tool messages (results from tool execution)
        if isinstance(message_chunk, ToolMessage):
            yield from self._tool_message(message_chunk)
            return

        # Process AI message chunks
        if isinstance(message_chunk, AIMessageChunk):
            yield from self._ai_chunk(message_chunk, source_node)

    def _tool_message(self, message_chunk: ToolMessage) -> Iterator[dict[str, Any]]:
        self.tool_results.append(
            {
                "type": "tool",
                "content": message_chunk.content,
            }
        )
        self.all_messages.append(message_chunk)
        # Signal tool execution ended (matched by call id)
        tool_call_id = getattr(message_chunk, "tool_call_id", None)
        tool_name = getattr(message_chunk, "name", None)
        if tool_call_id and tool_call_id in self.pending_tool_calls:
            self.pending_tool_calls.discard(tool_call_id)
            if tool_name:
                yield {"type": "tool_end", "tool": tool_name}

    def _ai_chunk(
        self, message_chunk: AIMessageChunk, source_node: str
    ) -> Iterator[dict[str, Any]]:
        # Extract usage metadata immediately
        self.chunk_count += 1
        self.totals.add_from(message_chunk)

        # Filter out non-chat node output (plan classifier, plan generation)
        if source_node and source_node != CHAT_NODE_NAME:
            return

        # Collect AIMessage chunks for metadata extraction (chat node only)
        self.all_messages.append(message_chunk)

        # Check for tool calls starting
        if message_chunk.tool_calls or message_chunk.tool_call_chunks:
            yield from self._tool_starts(message_chunk)
            return

        # Process content
        if message_chunk.content:
            yield from self._content(message_chunk)

    def _tool_starts(self, message_chunk: AIMessageChunk) -> Iterator[dict[str, Any]]:
        """tool_start events for tool calls first seen in this chunk."""
        # Get tool names and args from tool_calls or tool_call_chunks
        # tool_calls has complete args as dict, tool_call_chunks has partial args as string
        tool_infos: list[tuple[str, str, dict[str, Any]]] = []
        if message_chunk.tool_calls:
            for tool_call in message_chunk.tool_calls:
                tc_id = tool_call.get("id")
                tc_name = tool_call.get("name")
                tc_args = tool_call.get("args", {})
                if tc_id and tc_name is not None and isinstance(tc_args, dict):
                    tool_infos.append((tc_id, tc_name, tc_args))
        elif message_chunk.tool_call_chunks:
            # tool_call_chunks have partial args - we just emit tool_start
            # when we see the call id + name (continuation chunks
            # carry neither). Details come from tool_calls later.
            for tc_chunk in message_chunk.tool_call_chunks:
                chunk_id: str | None = tc_chunk.get("id")
                chunk_name: str | None = tc_chunk.get("name")
                if chunk_id and chunk_name and chunk_id not in self.pending_tool_calls:
                    self.pending_tool_calls.add(chunk_id)
                    tool_start_event: dict[str, Any] = {
                        "type": "tool_start",
                        "tool": chunk_name,
                    }
                    if chunk_name in TOOL_METADATA:
                        tool_start_event["metadata"] = TOOL_METADATA[chunk_name]
                    yield tool_start_event
            return

        for tc_id, tool_name, tool_args in tool_infos:
            if tc_id not in self.pending_tool_calls:
                self.pending_tool_calls.add(tc_id)
                # Include relevant detail based on tool type
                tool_event: dict[str, Any] = {
                    "type": "tool_start",
                    "tool": tool_name,
                }
                # Add tool-specific detail (only available from complete tool_calls)
                detail = extract_tool_detail(tool_name, tool_args)
                if detail:
                    tool_event["detail"] = detail
                # Include metadata for frontend display
                if tool_name in TOOL_METADATA:
                    tool_event["metadata"] = TOOL_METADATA[tool_name]
                yield tool_event

    def _content(self, message_chunk: AIMessageChunk) -> Iterator[dict[str, Any]]:
        """thinking/token events for a content-bearing chat chunk."""
        chunk_count = self.chunk_count
        # Debug: Log raw content structure occasionally
        if chunk_count <= 5:
            content_type = type(message_chunk.content).__name__
            content_preview = str(message_chunk.content)[:200]
            logger.debug(
                "Raw chunk content",
                extra={
                    "chunk_number": chunk_count,
                    "content_type": content_type,
                    "content_preview": content_preview,
                },
            )

        # Extract thinking and text separately
        thinking, text_content = extract_thinking_and_text(message_chunk.content)

        # Log extraction for first few chunks to diagnose streaming issues
        if chunk_count <= 3:
            logger.info(
                "Chunk extraction result",
                extra={
                    "chunk_count": chunk_count,
                    "has_thinking": bool(thinking),
                    "thinking_len": len(thinking) if thinking else 0,
                    "has_text": bool(text_content),
                    "text_len": len(text_content) if text_content else 0,
                    "text_preview": text_content[:100] if text_content else None,
                    "raw_type": type(message_chunk.content).__name__,
                },
            )

        # Accumulate thinking content and yield updates
        if thinking:
            self.accumulated_thinking += thinking
            yield {"type": "thinking", "text": self.accumulated_thinking}

        # Process regular text content
        if text_content:
            # Handle echoed MSG_CONTEXT (history context) - may span multiple chunks
            text_content = self.msg_context.feed(text_content)
            # Add to full response and yield token
            self.full_response += text_content
            if text_content:
                self.token_yield_count += 1
                yield {"type": "token", "text": text_content}

    def finish(self, turn_started: float) -> Iterator[dict[str, Any]]:
        """Flush held-back text, then the final event with the turn's totals."""
        # Handle any remaining carryover (wasn't part of a marker)
        carryover = self.msg_context.carryover
        if carryover and not self.msg_context.in_msg_context:
            self.full_response += carryover
            self.token_yield_count += 1
            yield {"type": "token", "text": carryover}

        # Apply tool call JSON cleanup to the full response
        clean_content = clean_tool_call_json(self.full_response)

        # Log token streaming summary
        if self.token_yield_count > 0 or len(self.full_response) > 0:
            logger.info(
                "Token streaming summary",
                extra={
                    "token_yield_count": self.token_yield_count,
                    "full_response_length": len(self.full_response),
                    "clean_content_length": len(clean_content),
                    "chunk_count": self.chunk_count,
                },
            )

        usage_info = build_usage_info(
            self.totals,
            self.all_messages,
            round((time.monotonic() - turn_started) * 1000),
        )

        # Final yield with all accumulated data
        yield {
            "type": "final",
            "content": clean_content,
            "tool_results": self.tool_results,
            "usage_info": usage_info,
            "result_messages": self.all_messages,
        }


def iter_token_stream(
    stream: Iterable[Any], messages: list[BaseMessage], turn_started: float
) -> Generator[str | tuple[str, list[dict[str, Any]], dict[str, Any], list[BaseMessage]]]:
    """Text tokens from a stream_mode="messages" graph stream, then the totals.

    Yields each chat-node text token, and finally
    (full_response, tool_results, usage_info, all_messages).
    """
    # Accumulate full response text
    full_response = ""
    # Capture tool results for server-side extraction (e.g., generated images)
    tool_results: list[dict[str, Any]] = []
    # Collect all messages for metadata tool arg extraction
    all_messages: list[BaseMessage] = list(messages)
    # Track token counts as we stream (memory efficient - only store numbers, not message objects)
    totals = TokenTotals()
    chunk_count = 0

    for event in stream:
        # event is a tuple of (message_chunk, metadata) in messages mode
        if not (isinstance(event, tuple) and len(event) >= 1):
            continue
        message_chunk = event[0]
        event_meta = event[1] if len(event) >= 2 and isinstance(event[1], dict) else {}
        source_node = event_meta.get("langgraph_node", "")

        # Capture tool messages (results from tool execution)
        if isinstance(message_chunk, ToolMessage):
            tool_results.append(
                {
                    "type": "tool",
                    "content": message_chunk.content,
                }
            )
            all_messages.append(message_chunk)
            continue

        # Only yield content from AI message chunks (not tool calls or tool results)
        if not isinstance(message_chunk, AIMessageChunk):
            continue
        # Extract usage metadata immediately (don't store the message object)
        chunk_count += 1
        totals.add_from(message_chunk)

        # Filter out non-chat node output (plan classifier, plan generation)
        if source_node and source_node != CHAT_NODE_NAME:
            continue

        # Collect AIMessage chunks for metadata extraction (chat node only)
        all_messages.append(message_chunk)

        # Skip chunks that are only tool calls (no text content)
        if message_chunk.tool_calls or message_chunk.tool_call_chunks:
            continue
        content = extract_text_content(message_chunk.content) if message_chunk.content else ""
        if content:
            full_response += content
            yield content

    # Log a warning if we didn't find any usage metadata (should be rare)
    if not totals.any and chunk_count > 0:
        logger.warning(
            "No usage metadata found in streaming chunks",
            extra={
                "chunk_count": chunk_count,
                "note": "This is unusual - Gemini streaming chunks typically include usage_metadata. Cost tracking may be inaccurate for this request.",
            },
        )

    usage_info = build_usage_info(
        totals, all_messages, round((time.monotonic() - turn_started) * 1000)
    )

    if totals.any:
        logger.debug(
            "Usage metadata aggregated from streaming chunks",
            extra={
                "input_tokens": totals.input_tokens,
                "output_tokens": totals.output_tokens,
                "cached_input_tokens": totals.cached_tokens,
                "tool_rounds": usage_info["tool_rounds"],
                "tool_call_count": usage_info["tool_call_count"],
                "chunk_count": chunk_count,
            },
        )

    # Final yield: (content, tool_results, usage_info, all_messages) for server processing
    yield (full_response, tool_results, usage_info, all_messages)
