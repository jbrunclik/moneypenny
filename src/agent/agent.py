"""ChatAgent class and title generation for the chat system.

This module contains the main ChatAgent class that orchestrates conversations
with the LLM, as well as the generate_title function for conversation titles.
"""

import contextvars
from collections.abc import Generator
from typing import Any, cast

from google.api_core.exceptions import GoogleAPIError
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_google_genai import ChatGoogleGenerativeAI

from src.agent.content import (
    clean_tool_call_json,
    extract_metadata_from_response,
    extract_text_content,
    extract_thinking_and_text,
)
from src.agent.graph import create_chat_graph
from src.agent.prompts import get_system_prompt
from src.agent.tool_display import TOOL_METADATA, extract_tool_detail
from src.agent.tools import get_tools_for_request
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Contextvar to hold the current planner dashboard data
# This allows the refresh_planner_dashboard tool to update the context mid-conversation
_planner_dashboard_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "_planner_dashboard_context", default=None
)


class ChatAgent:
    """Agent for handling chat conversations with tool support."""

    def __init__(
        self,
        model_name: str = Config.DEFAULT_MODEL,
        with_tools: bool = True,
        include_thoughts: bool = False,
        anonymous_mode: bool = False,
        is_planning: bool = False,
        is_autonomous: bool = False,
        agent_context: dict[str, Any] | None = None,
        tools: list[Any] | None = None,
    ) -> None:
        self.model_name = model_name
        self.with_tools = with_tools
        self.include_thoughts = include_thoughts
        self.anonymous_mode = anonymous_mode
        self.is_planning = is_planning
        self.is_autonomous = is_autonomous
        self.agent_context = agent_context
        # Use provided tools, or get filtered tools based on mode
        if tools is not None:
            active_tools = tools
        elif is_autonomous and agent_context and "tools" in agent_context:
            # Interactive agent conversation - use agent's tool permissions
            # Note: tools=None means all tools, tools=[] means no extra integrations
            agent_tools = agent_context.get("tools")
            active_tools = get_tools_for_request(
                anonymous_mode, is_planning, agent_tool_permissions=agent_tools
            )
        else:
            active_tools = get_tools_for_request(anonymous_mode, is_planning)
        logger.debug(
            "Creating ChatAgent",
            extra={
                "model": model_name,
                "with_tools": with_tools,
                "include_thoughts": include_thoughts,
                "anonymous_mode": anonymous_mode,
                "is_planning": is_planning,
                "is_autonomous": is_autonomous,
                "tool_names": [t.name for t in active_tools],
            },
        )
        self.graph = create_chat_graph(
            model_name,
            with_tools=with_tools,
            include_thoughts=include_thoughts,
            tools=active_tools,
            is_autonomous=is_autonomous,
        ).compile()

    def _build_message_content(
        self, text: str, files: list[dict[str, Any]] | None = None
    ) -> str | list[str | dict[Any, Any]]:
        """Build message content for LangChain.

        Args:
            text: Plain text message
            files: Optional list of file attachments

        Returns:
            For text-only: the string
            For multimodal: list of content blocks for LangChain
        """
        if not files:
            return text

        # Build multimodal content blocks
        blocks: list[str | dict[Any, Any]] = []

        # Add text block if present
        if text:
            blocks.append({"type": "text", "text": text})

        # Add file blocks
        for file in files:
            mime_type = file.get("type", "application/octet-stream")
            data = file.get("data", "")

            if mime_type.startswith("image/"):
                # Image block for Gemini
                blocks.append(
                    {
                        "type": "image",
                        "base64": data,
                        "mime_type": mime_type,
                    }
                )
            elif mime_type == "application/pdf":
                # PDF - Gemini supports inline PDFs
                blocks.append(
                    {
                        "type": "image",  # LangChain uses image type for PDFs too
                        "base64": data,
                        "mime_type": mime_type,
                    }
                )
            else:
                # Text files - include as text block
                try:
                    import base64
                    import binascii

                    decoded = base64.b64decode(data).decode("utf-8")
                    file_name = file.get("name", "file")
                    blocks.append(
                        {
                            "type": "text",
                            "text": f"\n--- Content of {file_name} ---\n{decoded}\n--- End of {file_name} ---\n",
                        }
                    )
                except (binascii.Error, UnicodeDecodeError):
                    # If decoding fails (invalid base64 or non-UTF-8), skip the file
                    pass

        return blocks if blocks else text

    def _format_message_with_metadata(self, msg: dict[str, Any]) -> str:
        """Format message content with metadata context for LLM.

        Enriches message content with temporal context, file references,
        and tool usage summaries as a JSON metadata block. Uses the same
        <!-- METADATA: --> format as assistant response metadata for consistency.

        Args:
            msg: Enriched message dict with 'role', 'content', and 'metadata' keys

        Returns:
            Formatted string with JSON metadata block prefixed to content
        """
        import json

        metadata = msg.get("metadata", {})
        content: str = msg["content"]

        # Build compact metadata dict with only present fields
        meta_dict: dict[str, Any] = {}

        # Session gap indicator (if present)
        if metadata.get("session_gap"):
            meta_dict["session_gap"] = metadata["session_gap"]

        # Timestamps
        if metadata.get("timestamp"):
            meta_dict["timestamp"] = metadata["timestamp"]
        if metadata.get("relative_time"):
            meta_dict["relative_time"] = metadata["relative_time"]

        # Files (for user messages) - compact format for direct tool access
        if metadata.get("files"):
            meta_dict["files"] = [
                {
                    "name": f["name"],
                    "type": f["type"],
                    "id": f"{f['message_id']}:{f['file_index']}",
                }
                for f in metadata["files"]
            ]

        # Tool usage (for assistant messages)
        if metadata.get("tools_used"):
            meta_dict["tools_used"] = metadata["tools_used"]
        if metadata.get("tool_summary"):
            meta_dict["tool_summary"] = metadata["tool_summary"]

        # Return with metadata block if we have any metadata
        if meta_dict:
            json_str = json.dumps(meta_dict, separators=(",", ":"))
            return f"<!-- METADATA: {json_str} -->\n{content}"
        return content

    def _build_messages(
        self,
        text: str,
        files: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        force_tools: list[str] | None = None,
        user_name: str | None = None,
        user_id: str | None = None,
        custom_instructions: str | None = None,
        is_planning: bool = False,
        dashboard_data: dict[str, Any] | None = None,
    ) -> list[BaseMessage]:
        """Build the messages list from history and user message."""
        messages: list[BaseMessage] = []

        # Always add system prompt (with tool instructions if tools are enabled)
        # In anonymous mode, user memories are not included in the prompt
        # Check for updated dashboard context from refresh_planner_dashboard tool
        refreshed_dashboard = _planner_dashboard_context.get()
        messages.append(
            SystemMessage(
                content=get_system_prompt(
                    self.with_tools,
                    force_tools=force_tools,
                    user_name=user_name,
                    user_id=user_id,
                    custom_instructions=custom_instructions,
                    anonymous_mode=self.anonymous_mode,
                    is_planning=is_planning,
                    dashboard_data=dashboard_data,
                    planner_dashboard_context=refreshed_dashboard,
                    is_autonomous=self.is_autonomous,
                    agent_context=self.agent_context,
                )
            )
        )

        if history:
            for msg in history:
                # Format content with metadata context (timestamps, files, tools)
                formatted_content = self._format_message_with_metadata(msg)

                if msg["role"] == "user":
                    # User messages may have file attachments (handled separately)
                    content = self._build_message_content(formatted_content, msg.get("files"))
                    messages.append(HumanMessage(content=content))
                elif msg["role"] == "assistant":
                    # Assistant messages are always text
                    messages.append(AIMessage(content=formatted_content))

        # Add the current user message
        content = self._build_message_content(text, files)
        messages.append(HumanMessage(content=content))

        return messages

    def chat_batch(
        self,
        text: str,
        files: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        force_tools: list[str] | None = None,
        user_name: str | None = None,
        user_id: str | None = None,
        custom_instructions: str | None = None,
        is_planning: bool = False,
        dashboard_data: dict[str, Any] | None = None,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        """
        Send a message and get a response (non-streaming).

        Args:
            text: The user's message text
            files: Optional list of file attachments
            history: Optional list of previous messages with 'role', 'content', and 'files' keys
            force_tools: Optional list of tool names that must be used
            user_name: Optional user name from JWT for personalized responses
            user_id: Optional user ID for memory retrieval and injection
            custom_instructions: Optional user-provided custom instructions for LLM behavior
            is_planning: If True, use planner-specific system prompt with dashboard context
            dashboard_data: Dashboard data to inject into planner prompt (required if is_planning=True)

        Returns:
            Tuple of (response_text, tool_results, usage_info)
        """
        messages = self._build_messages(
            text,
            files,
            history,
            force_tools=force_tools,
            user_name=user_name,
            user_id=user_id,
            custom_instructions=custom_instructions,
            is_planning=is_planning,
            dashboard_data=dashboard_data,
        )
        logger.debug(
            "Starting chat_batch",
            extra={
                "model": self.model_name,
                "message_length": len(text),
                "has_files": bool(files),
                "file_count": len(files) if files else 0,
                "force_tools": force_tools,
                "total_messages": len(messages),
            },
        )

        # Run the graph
        result = self.graph.invoke(cast(Any, {"messages": messages}))

        # Extract response (last AI message with actual content)
        response_text = ""
        for msg in reversed(result["messages"]):
            if isinstance(msg, AIMessage):
                text_content = extract_text_content(msg.content)
                if msg.tool_calls and not text_content:
                    continue
                text_content = clean_tool_call_json(text_content)
                if text_content:
                    response_text = text_content
                    break

        # Extract tool results
        tool_results: list[dict[str, Any]] = []
        for msg in result["messages"]:
            if isinstance(msg, ToolMessage):
                tool_results.append({"type": "tool", "content": msg.content})

        if tool_results:
            logger.info("Tool results captured", extra={"tool_result_count": len(tool_results)})

        # Aggregate usage metadata from all AIMessages
        total_input_tokens = 0
        total_output_tokens = 0
        for msg in result["messages"]:
            if isinstance(msg, AIMessage):
                if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                    usage = msg.usage_metadata
                    if isinstance(usage, dict):
                        input_tokens = usage.get("input_tokens", 0)
                        output_tokens = usage.get("output_tokens", 0)
                        if input_tokens > 0 or output_tokens > 0:
                            total_input_tokens += input_tokens
                            total_output_tokens += output_tokens
                            logger.debug(
                                "Found usage metadata in AIMessage",
                                extra={
                                    "input_tokens": input_tokens,
                                    "output_tokens": output_tokens,
                                },
                            )

        usage_info = {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
        }

        if total_input_tokens > 0 or total_output_tokens > 0:
            logger.debug(
                "Usage metadata aggregated",
                extra={
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                },
            )

        return response_text, tool_results, usage_info

    def stream_chat(
        self,
        text: str,
        files: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        force_tools: list[str] | None = None,
        user_name: str | None = None,
        user_id: str | None = None,
        custom_instructions: str | None = None,
        is_planning: bool = False,
        dashboard_data: dict[str, Any] | None = None,
    ) -> Generator[str | tuple[str, dict[str, Any], list[dict[str, Any]], dict[str, Any]]]:
        """
        Stream response tokens using LangGraph's stream method.

        Args:
            text: The user's message text
            files: Optional list of file attachments
            history: Optional list of previous messages with 'role', 'content', and 'files' keys
            force_tools: Optional list of tool names that must be used
            user_name: Optional user name from JWT for personalized responses
            user_id: Optional user ID for memory retrieval and injection
            custom_instructions: Optional user-provided custom instructions for LLM behavior

        Yields:
            - str: Text tokens for streaming display
            - tuple: Final (content, metadata, tool_results, usage_info) where:
              - content: Clean response text (metadata stripped)
              - metadata: Extracted metadata dict (sources, generated_images, etc.)
              - tool_results: List of tool message dicts for server-side processing
              - usage_info: Dict with 'input_tokens' and 'output_tokens'
        """
        messages = self._build_messages(
            text,
            files,
            history,
            force_tools=force_tools,
            user_name=user_name,
            user_id=user_id,
            custom_instructions=custom_instructions,
            is_planning=is_planning,
            dashboard_data=dashboard_data,
        )

        # Accumulate full response to extract metadata at the end
        full_response = ""
        # Buffer to detect metadata marker - we hold back chars until we're sure
        # they're not part of the metadata marker
        buffer = ""
        metadata_marker = "<!-- METADATA:"
        in_metadata = False
        # Capture tool results for server-side extraction (e.g., generated images)
        tool_results: list[dict[str, Any]] = []
        # Track token counts as we stream (memory efficient - only store numbers, not message objects)
        total_input_tokens = 0
        total_output_tokens = 0
        chunk_count = 0

        # Stream the graph execution with messages mode for token-level streaming
        for event in self.graph.stream(
            cast(Any, {"messages": messages}),
            stream_mode="messages",
        ):
            # event is a tuple of (message_chunk, metadata) in messages mode
            if isinstance(event, tuple) and len(event) >= 1:
                message_chunk = event[0]

                # Capture tool messages (results from tool execution)
                if isinstance(message_chunk, ToolMessage):
                    tool_results.append(
                        {
                            "type": "tool",
                            "content": message_chunk.content,
                        }
                    )
                    continue

                # Only yield content from AI message chunks (not tool calls or tool results)
                if isinstance(message_chunk, AIMessageChunk):
                    # Extract usage metadata immediately (don't store the message object)
                    chunk_count += 1
                    if hasattr(message_chunk, "usage_metadata") and message_chunk.usage_metadata:
                        usage = message_chunk.usage_metadata
                        if isinstance(usage, dict):
                            input_tokens = usage.get("input_tokens", 0)
                            output_tokens = usage.get("output_tokens", 0)
                            if input_tokens > 0 or output_tokens > 0:
                                total_input_tokens += input_tokens
                                total_output_tokens += output_tokens
                                logger.debug(
                                    "Found usage in chunk",
                                    extra={
                                        "input_tokens": input_tokens,
                                        "output_tokens": output_tokens,
                                    },
                                )

                    # Skip chunks that are only tool calls (no text content)
                    if message_chunk.tool_calls or message_chunk.tool_call_chunks:
                        continue
                    if message_chunk.content:
                        content = extract_text_content(message_chunk.content)
                        if content:
                            full_response += content

                            # If we've detected metadata, don't yield anything more
                            if in_metadata:
                                continue

                            # Add to buffer and check for metadata marker
                            buffer += content

                            # Check if buffer contains the start of metadata (HTML comment format)
                            if metadata_marker in buffer:
                                # Yield everything before the marker
                                marker_pos = buffer.find(metadata_marker)
                                if marker_pos > 0:
                                    yield buffer[:marker_pos].rstrip()
                                in_metadata = True
                                buffer = ""
                            elif len(buffer) > len(metadata_marker):
                                # Buffer is longer than marker, safe to yield the excess
                                safe_length = len(buffer) - len(metadata_marker)
                                yield buffer[:safe_length]
                                buffer = buffer[safe_length:]

        # Yield any remaining buffer that's not metadata
        if buffer and not in_metadata:
            # Final check - might end with partial marker or JSON
            clean, _ = extract_metadata_from_response(buffer)
            if clean and clean.strip():
                yield clean

        # Extract metadata and yield final tuple
        clean_content, metadata = extract_metadata_from_response(full_response)

        # Log a warning if we didn't find any usage metadata (should be rare)
        if total_input_tokens == 0 and total_output_tokens == 0 and chunk_count > 0:
            logger.warning(
                "No usage metadata found in streaming chunks",
                extra={
                    "chunk_count": chunk_count,
                    "note": "This is unusual - Gemini streaming chunks typically include usage_metadata. Cost tracking may be inaccurate for this request.",
                },
            )

        usage_info = {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
        }

        if total_input_tokens > 0 or total_output_tokens > 0:
            logger.debug(
                "Usage metadata aggregated from streaming chunks",
                extra={
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "chunk_count": chunk_count,
                },
            )

        # Final yield: (content, metadata, tool_results, usage_info) for server processing
        yield (clean_content, metadata, tool_results, usage_info)

    def stream_chat_events(
        self,
        text: str,
        files: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        force_tools: list[str] | None = None,
        user_name: str | None = None,
        user_id: str | None = None,
        custom_instructions: str | None = None,
        is_planning: bool = False,
        dashboard_data: dict[str, Any] | None = None,
    ) -> Generator[dict[str, Any]]:
        """Stream response events including thinking, tool calls, and tokens.

        This method yields structured events that can be sent to the frontend.
        It requires include_thoughts=True on the ChatAgent to receive thinking content.

        Args:
            text: The user's message text
            files: Optional list of file attachments
            history: Optional list of previous messages with 'role', 'content', and 'files' keys
            force_tools: Optional list of tool names that must be used
            user_name: Optional user name from JWT for personalized responses
            user_id: Optional user ID for memory retrieval and injection
            custom_instructions: Optional user-provided custom instructions for LLM behavior

        Yields:
            Events as dicts with 'type' field:
            - {"type": "thinking", "text": "..."} - Model's reasoning/thinking text
            - {"type": "tool_start", "tool": "tool_name"} - Tool execution starting
            - {"type": "tool_end", "tool": "tool_name"} - Tool execution finished
            - {"type": "token", "text": "..."} - Text token for streaming display
            - {"type": "final", "content": "...", "metadata": {...}, "tool_results": [...], "usage_info": {...}}
        """
        messages = self._build_messages(
            text,
            files,
            history,
            force_tools=force_tools,
            user_name=user_name,
            user_id=user_id,
            custom_instructions=custom_instructions,
            is_planning=is_planning,
            dashboard_data=dashboard_data,
        )

        # Accumulate full response to extract metadata at the end
        full_response = ""
        # Buffer to detect metadata marker
        buffer = ""
        metadata_marker = "<!-- METADATA:"
        in_metadata = False
        # Capture tool results for server-side extraction
        tool_results: list[dict[str, Any]] = []
        # Track token counts
        total_input_tokens = 0
        total_output_tokens = 0
        chunk_count = 0
        # Track active tool calls to detect when a tool is being executed
        pending_tool_calls: set[str] = set()
        # Accumulate thinking text across chunks
        accumulated_thinking = ""
        # Track token yields for debugging
        token_yield_count = 0

        # Stream the graph execution with messages mode for token-level streaming
        # Wrapped in try-except to handle executor shutdown gracefully
        try:
            for event in self.graph.stream(
                cast(Any, {"messages": messages}),
                stream_mode="messages",
            ):
                if isinstance(event, tuple) and len(event) >= 1:
                    message_chunk = event[0]

                # Capture tool messages (results from tool execution)
                if isinstance(message_chunk, ToolMessage):
                    tool_results.append(
                        {
                            "type": "tool",
                            "content": message_chunk.content,
                        }
                    )
                    # Signal tool execution ended
                    tool_name = getattr(message_chunk, "name", None)
                    if tool_name and tool_name in pending_tool_calls:
                        pending_tool_calls.discard(tool_name)
                        yield {"type": "tool_end", "tool": tool_name}
                    continue

                # Process AI message chunks
                if isinstance(message_chunk, AIMessageChunk):
                    # Extract usage metadata immediately
                    chunk_count += 1
                    if hasattr(message_chunk, "usage_metadata") and message_chunk.usage_metadata:
                        usage = message_chunk.usage_metadata
                        if isinstance(usage, dict):
                            input_tokens = usage.get("input_tokens", 0)
                            output_tokens = usage.get("output_tokens", 0)
                            if input_tokens > 0 or output_tokens > 0:
                                total_input_tokens += input_tokens
                                total_output_tokens += output_tokens

                    # Check for tool calls starting
                    if message_chunk.tool_calls or message_chunk.tool_call_chunks:
                        # Get tool names and args from tool_calls or tool_call_chunks
                        # tool_calls has complete args as dict, tool_call_chunks has partial args as string
                        tool_infos: list[tuple[str, dict[str, Any]]] = []
                        if message_chunk.tool_calls:
                            for tool_call in message_chunk.tool_calls:
                                tc_name = tool_call.get("name")
                                tc_args = tool_call.get("args", {})
                                if tc_name is not None and isinstance(tc_args, dict):
                                    tool_infos.append((tc_name, tc_args))
                        elif message_chunk.tool_call_chunks:
                            # tool_call_chunks have partial args - we just emit tool_start
                            # when we see the tool name. Details will come from tool_calls later.
                            for tc_chunk in message_chunk.tool_call_chunks:
                                chunk_name: str | None = tc_chunk.get("name")
                                if chunk_name and chunk_name not in pending_tool_calls:
                                    pending_tool_calls.add(chunk_name)
                                    tool_start_event: dict[str, Any] = {
                                        "type": "tool_start",
                                        "tool": chunk_name,
                                    }
                                    if chunk_name in TOOL_METADATA:
                                        tool_start_event["metadata"] = TOOL_METADATA[chunk_name]
                                    yield tool_start_event
                            continue

                        for tool_name, tool_args in tool_infos:
                            if tool_name not in pending_tool_calls:
                                pending_tool_calls.add(tool_name)
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
                        continue

                    # Process content
                    if message_chunk.content:
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

                        # Debug: Log the extracted content
                        if thinking:
                            logger.debug(
                                "Extracted thinking content",
                                extra={
                                    "thinking_length": len(thinking),
                                    "thinking_preview": thinking[:100]
                                    if len(thinking) > 100
                                    else thinking,
                                },
                            )

                        # Accumulate thinking content and yield updates
                        if thinking:
                            accumulated_thinking += thinking
                            yield {"type": "thinking", "text": accumulated_thinking}

                        # Process regular text content
                        if text_content:
                            full_response += text_content

                            # If we've detected metadata, don't yield anything more
                            if in_metadata:
                                continue

                            # Add to buffer and check for metadata marker
                            buffer += text_content

                            # Check if buffer contains the start of metadata
                            if metadata_marker in buffer:
                                marker_pos = buffer.find(metadata_marker)
                                if marker_pos > 0:
                                    token_yield_count += 1
                                    yield {"type": "token", "text": buffer[:marker_pos].rstrip()}
                                in_metadata = True
                                buffer = ""
                            elif len(buffer) > len(metadata_marker):
                                safe_length = len(buffer) - len(metadata_marker)
                                token_yield_count += 1
                                yield {"type": "token", "text": buffer[:safe_length]}
                                buffer = buffer[safe_length:]
        except RuntimeError as e:
            # Handle executor shutdown gracefully (e.g., during server restart)
            # Python's ThreadPoolExecutor raises generic RuntimeError with specific messages
            # when submit() is called after shutdown - there's no specific exception class
            error_msg = str(e).lower()
            if "cannot schedule new futures" in error_msg and "shutdown" in error_msg:
                logger.warning(
                    "Streaming interrupted by executor shutdown (likely server restart)",
                    extra={
                        "accumulated_response_length": len(full_response),
                        "has_tool_results": bool(tool_results),
                    },
                )
                # Continue to yield accumulated content and final event
            else:
                # Re-raise other RuntimeErrors
                raise

        # Yield any remaining buffer that's not metadata
        if buffer and not in_metadata:
            clean, _ = extract_metadata_from_response(buffer)
            if clean and clean.strip():
                token_yield_count += 1
                yield {"type": "token", "text": clean}

        # Extract metadata
        clean_content, metadata = extract_metadata_from_response(full_response)

        # Log token streaming summary
        if token_yield_count > 0 or len(full_response) > 0:
            logger.info(
                "Token streaming summary",
                extra={
                    "token_yield_count": token_yield_count,
                    "full_response_length": len(full_response),
                    "clean_content_length": len(clean_content),
                    "chunk_count": chunk_count,
                },
            )

        usage_info = {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
        }

        # Final yield with all accumulated data
        yield {
            "type": "final",
            "content": clean_content,
            "metadata": metadata,
            "tool_results": tool_results,
            "usage_info": usage_info,
        }


def generate_title(user_message: str, assistant_response: str) -> str:
    """
    Generate a concise title for a conversation using Gemini.

    Args:
        user_message: The first user message
        assistant_response: The assistant's response

    Returns:
        A short, descriptive title (max ~50 chars)
    """
    logger.debug("Generating conversation title")
    # Use Flash model for fast, cheap title generation
    model = ChatGoogleGenerativeAI(
        model=Config.TITLE_GENERATION_MODEL,
        google_api_key=Config.GEMINI_API_KEY,
        temperature=Config.TITLE_GENERATION_TEMPERATURE,
    )

    # Truncate context to avoid sending too much data
    max_context = Config.TITLE_CONTEXT_MAX_LENGTH
    prompt = f"""Generate a very short, concise title (3-6 words max) for this conversation.
The title should capture the main topic or intent.
Do NOT use quotes around the title.
Do NOT include prefixes like "Title:" or "Topic:".
Just output the title text directly.

User: {user_message[:max_context]}
Assistant: {assistant_response[:max_context]}

Title:"""

    try:
        response = model.invoke([HumanMessage(content=prompt)])
        title = extract_text_content(response.content).strip()
        # Clean up any quotes or prefixes that slipped through
        title = title.strip("\"'")
        if title.lower().startswith("title:"):
            title = title[6:].strip()
        # Truncate if too long
        if len(title) > Config.TITLE_MAX_LENGTH:
            title = title[: Config.TITLE_TRUNCATE_LENGTH] + "..."
        final_title = title or user_message[: Config.TITLE_FALLBACK_LENGTH]
        logger.debug("Title generated", extra={"title": final_title})
        return final_title
    except (GoogleAPIError, ValueError, TimeoutError) as e:
        # Fallback to truncated message on API or parsing errors
        logger.warning("Title generation failed, using fallback", extra={"error": str(e)})
        fallback_len = Config.TITLE_FALLBACK_LENGTH
        return user_message[:fallback_len] + ("..." if len(user_message) > fallback_len else "")
