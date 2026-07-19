"""ChatAgent class and title generation for the chat system.

This module contains the main ChatAgent class that orchestrates conversations
with the LLM, as well as the generate_title function for conversation titles.
"""

import contextvars
from collections.abc import Generator, Iterable, Mapping
from typing import Any, cast

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
    extract_text_content,
    extract_thinking_and_text,
)
from src.agent.context_cache import CacheProfile
from src.agent.graph import CHAT_NODE_NAME, create_chat_graph
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


def _usage_tokens(usage: Mapping[str, Any]) -> tuple[int, int, int]:
    """Extract (input, output, cache_read) from a usage_metadata dict.

    cache_read is the subset of input_tokens served from Gemini's context
    cache (billed at the discounted cached_input rate). Streaming chunks are
    delta-encoded - input_tokens and cache_read arrive once per LLM call -
    so summing across chunks/messages is correct.
    """
    details = usage.get("input_token_details")
    cache_read = details.get("cache_read", 0) if isinstance(details, dict) else 0
    return usage.get("input_tokens", 0), usage.get("output_tokens", 0), cache_read


def _tool_telemetry(messages: Iterable[BaseMessage]) -> tuple[int, int]:
    """Count (tool_rounds, tool_call_count) over a turn's messages/chunks.

    tool_rounds: distinct LLM responses (by message id) that requested tool
    calls. This is the round-multiplication multiplier - each one re-invokes
    the model with the accumulated context, so it drives input-token cost far
    more than the size of any single tool payload.
    tool_call_count: number of tool executions (ToolMessages) in the turn.

    Streaming chunks of one response share an id (verified for Gemini), so
    deduping by id counts each round once however many chunks carried the
    tool call. Full messages (batch path) each have their own id too.
    """
    round_ids: set[Any] = set()
    tool_execs = 0
    for m in messages:
        if isinstance(m, ToolMessage):
            tool_execs += 1
        elif isinstance(m, AIMessage | AIMessageChunk) and (
            getattr(m, "tool_calls", None) or getattr(m, "tool_call_chunks", None)
        ):
            round_ids.add(m.id or id(m))
    return len(round_ids), tool_execs


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
        is_sports: bool = False,
        sports_context: dict[str, Any] | None = None,
        is_language: bool = False,
        language_context: dict[str, Any] | None = None,
    ) -> None:
        from src.agent.context_cache import get_cached_content_name

        self.model_name = model_name
        self.with_tools = with_tools
        self.include_thoughts = include_thoughts
        self.anonymous_mode = anonymous_mode
        self.is_planning = is_planning
        self.is_autonomous = is_autonomous
        self.agent_context = agent_context
        self.is_sports = is_sports
        self.sports_context = sports_context
        self.is_language = is_language
        self.language_context = language_context
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
            active_tools = get_tools_for_request(
                anonymous_mode, is_planning, is_sports=is_sports, is_language=is_language
            )

        # Determine cache profile and get cached content name
        self._cached_content_name: str | None = None
        cache_profile = self._get_cache_profile()
        if cache_profile and with_tools and active_tools:
            self._cached_content_name = get_cached_content_name(
                cache_profile, model_name, active_tools
            )

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
                "cached": self._cached_content_name is not None,
            },
        )
        from src.agent.graph import compile_graph

        self.graph = compile_graph(
            create_chat_graph(
                model_name,
                with_tools=with_tools,
                include_thoughts=include_thoughts,
                tools=active_tools,
                is_autonomous=is_autonomous,
                cached_content=self._cached_content_name,
            )
        )

    def _get_cache_profile(self) -> CacheProfile | None:
        """Determine the cache profile based on agent mode.

        Returns None for modes incompatible with caching (autonomous agents,
        no-tools mode).
        """
        # No caching for autonomous agents (variable tools) or no-tools mode
        if self.is_autonomous or not self.with_tools:
            return None
        if self.is_sports:
            return CacheProfile.SPORTS
        if self.is_language:
            return CacheProfile.LANGUAGE
        if self.is_planning:
            return CacheProfile.PLANNING
        if self.anonymous_mode:
            return CacheProfile.ANONYMOUS
        return CacheProfile.STANDARD

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
            elif mime_type.startswith("video/"):
                # Videos go via the Gemini Files API (inline limit is ~20MB).
                # The URI is attached by attach_gemini_file_uris() before the
                # agent runs; absence means the upload failed.
                uri = file.get("gemini_file_uri")
                if uri:
                    blocks.append({"type": "media", "file_uri": uri, "mime_type": mime_type})
                else:
                    error = file.get("gemini_upload_error", "processing failed")
                    name = file.get("name", "video")
                    blocks.append(
                        {
                            "type": "text",
                            "text": f"[Video '{name}' could not be attached: {error}. "
                            "Tell the user the video could not be processed.]",
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
        and tool usage summaries as a JSON metadata block. Uses a distinct
        <!-- MSG_CONTEXT: --> marker (different from response <!-- METADATA: -->)
        to prevent the LLM from echoing this format in its responses.

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

        # Timestamps (absolute only — a recomputed relative time would change
        # the serialized bytes every turn and defeat history prefix caching)
        if metadata.get("timestamp"):
            meta_dict["timestamp"] = metadata["timestamp"]

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
        # Use MSG_CONTEXT marker (distinct from response METADATA) to prevent echoing
        if meta_dict:
            json_str = json.dumps(meta_dict, separators=(",", ":"))
            return f"<!-- MSG_CONTEXT: {json_str} -->\n{content}"
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
        is_sports: bool = False,
        sports_context: dict[str, Any] | None = None,
        is_language: bool = False,
        language_context: dict[str, Any] | None = None,
    ) -> list[BaseMessage]:
        """Build the messages list from history and user message."""
        from src.agent.prompts import get_dynamic_prompt_parts

        messages: list[BaseMessage] = []

        # Check for updated dashboard context from refresh_planner_dashboard tool
        refreshed_dashboard = _planner_dashboard_context.get()

        # In cached mode the static system prompt + tools live in the Gemini
        # cache, so the per-request dynamic context goes as a HumanMessage. We
        # defer it to the TAIL (just before the current user message) instead of
        # the head: a volatile message at position 0 would change the request
        # prefix every turn and prevent Gemini's implicit caching from reusing
        # the (stable) conversation history that follows. In uncached mode the
        # SystemMessage carries everything and stays at position 0.
        dynamic_context_msg: HumanMessage | None = None
        if self._cached_content_name:
            dynamic = get_dynamic_prompt_parts(
                force_tools=force_tools,
                user_name=user_name,
                user_id=user_id,
                custom_instructions=custom_instructions,
                anonymous_mode=self.anonymous_mode,
                is_planning=is_planning,
                dashboard_data=dashboard_data,
                planner_dashboard_context=refreshed_dashboard,
                is_sports=is_sports,
                sports_context=sports_context,
                is_language=is_language,
                language_context=language_context,
            )
            dynamic_context_msg = HumanMessage(content=f"[CONTEXT]\n{dynamic}\n[/CONTEXT]")
        else:
            # Uncached mode: full SystemMessage with everything, at the head
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
                        is_sports=is_sports,
                        sports_context=sports_context,
                        is_language=is_language,
                        language_context=language_context,
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

        # Append the deferred dynamic context (cached mode) right before the
        # current user message, keeping the volatile content at the tail.
        if dynamic_context_msg is not None:
            messages.append(dynamic_context_msg)

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
        conversation_id: str | None = None,
        is_sports: bool = False,
        sports_context: dict[str, Any] | None = None,
        is_language: bool = False,
        language_context: dict[str, Any] | None = None,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any], list[BaseMessage]]:
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
            is_sports: If True, use sports trainer system prompt
            sports_context: Sports context dict with program info

        Returns:
            Tuple of (response_text, tool_results, usage_info, result_messages)
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
            is_sports=is_sports,
            sports_context=sports_context,
            is_language=is_language,
            language_context=language_context,
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
        from src.agent.graph import get_graph_config

        config = get_graph_config()
        result = self.graph.invoke(cast(Any, {"messages": messages}), config=config)
        result_messages: list[BaseMessage] = result["messages"]

        # Extract response (last AI message with actual content)
        response_text = ""
        for msg in reversed(result_messages):
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
        for msg in result_messages:
            if isinstance(msg, ToolMessage):
                tool_results.append({"type": "tool", "content": msg.content})

        if tool_results:
            logger.info("Tool results captured", extra={"tool_result_count": len(tool_results)})

        # Aggregate usage metadata from all AIMessages
        total_input_tokens = 0
        total_output_tokens = 0
        total_cached_tokens = 0
        for msg in result_messages:
            if isinstance(msg, AIMessage):
                if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                    usage = msg.usage_metadata
                    if isinstance(usage, dict):
                        input_tokens, output_tokens, cache_read = _usage_tokens(usage)
                        if input_tokens > 0 or output_tokens > 0:
                            total_input_tokens += input_tokens
                            total_output_tokens += output_tokens
                            total_cached_tokens += cache_read
                            logger.debug(
                                "Found usage metadata in AIMessage",
                                extra={
                                    "input_tokens": input_tokens,
                                    "output_tokens": output_tokens,
                                    "cache_read": cache_read,
                                },
                            )

        tool_rounds, tool_call_count = _tool_telemetry(result_messages)
        usage_info = {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "cached_input_tokens": total_cached_tokens,
            "tool_rounds": tool_rounds,
            "tool_call_count": tool_call_count,
        }

        if total_input_tokens > 0 or total_output_tokens > 0:
            logger.debug(
                "Usage metadata aggregated",
                extra={
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "cached_input_tokens": total_cached_tokens,
                    "tool_rounds": tool_rounds,
                    "tool_call_count": tool_call_count,
                },
            )

        return response_text, tool_results, usage_info, result_messages

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
        conversation_id: str | None = None,
        is_sports: bool = False,
        sports_context: dict[str, Any] | None = None,
        is_language: bool = False,
        language_context: dict[str, Any] | None = None,
    ) -> Generator[str | tuple[str, list[dict[str, Any]], dict[str, Any], list[BaseMessage]]]:
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
            - tuple: Final (content, tool_results, usage_info, result_messages) where:
              - content: Clean response text
              - tool_results: List of tool message dicts for server-side processing
              - usage_info: Dict with 'input_tokens' and 'output_tokens'
              - result_messages: All messages from the graph for metadata extraction
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
            is_sports=is_sports,
            sports_context=sports_context,
            is_language=is_language,
            language_context=language_context,
        )

        # Accumulate full response text
        full_response = ""
        # Capture tool results for server-side extraction (e.g., generated images)
        tool_results: list[dict[str, Any]] = []
        # Collect all messages for metadata tool arg extraction
        all_messages: list[BaseMessage] = list(messages)
        # Track token counts as we stream (memory efficient - only store numbers, not message objects)
        total_input_tokens = 0
        total_output_tokens = 0
        total_cached_tokens = 0
        chunk_count = 0

        # Stream the graph execution with messages mode for token-level streaming
        from src.agent.graph import get_graph_config

        config = get_graph_config()
        for event in self.graph.stream(
            cast(Any, {"messages": messages}),
            config=config,
            stream_mode="messages",
        ):
            # event is a tuple of (message_chunk, metadata) in messages mode
            if isinstance(event, tuple) and len(event) >= 1:
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
                if isinstance(message_chunk, AIMessageChunk):
                    # Extract usage metadata immediately (don't store the message object)
                    chunk_count += 1
                    if hasattr(message_chunk, "usage_metadata") and message_chunk.usage_metadata:
                        usage = message_chunk.usage_metadata
                        if isinstance(usage, dict):
                            input_tokens, output_tokens, cache_read = _usage_tokens(usage)
                            if input_tokens > 0 or output_tokens > 0:
                                total_input_tokens += input_tokens
                                total_output_tokens += output_tokens
                                total_cached_tokens += cache_read

                    # Filter out non-chat node output (plan classifier, plan generation)
                    if source_node and source_node != CHAT_NODE_NAME:
                        continue

                    # Collect AIMessage chunks for metadata extraction (chat node only)
                    all_messages.append(message_chunk)

                    # Skip chunks that are only tool calls (no text content)
                    if message_chunk.tool_calls or message_chunk.tool_call_chunks:
                        continue
                    if message_chunk.content:
                        content = extract_text_content(message_chunk.content)
                        if content:
                            full_response += content
                            yield content

        # Log a warning if we didn't find any usage metadata (should be rare)
        if total_input_tokens == 0 and total_output_tokens == 0 and chunk_count > 0:
            logger.warning(
                "No usage metadata found in streaming chunks",
                extra={
                    "chunk_count": chunk_count,
                    "note": "This is unusual - Gemini streaming chunks typically include usage_metadata. Cost tracking may be inaccurate for this request.",
                },
            )

        tool_rounds, tool_call_count = _tool_telemetry(all_messages)
        usage_info = {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "cached_input_tokens": total_cached_tokens,
            "tool_rounds": tool_rounds,
            "tool_call_count": tool_call_count,
        }

        if total_input_tokens > 0 or total_output_tokens > 0:
            logger.debug(
                "Usage metadata aggregated from streaming chunks",
                extra={
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "cached_input_tokens": total_cached_tokens,
                    "tool_rounds": tool_rounds,
                    "tool_call_count": tool_call_count,
                    "chunk_count": chunk_count,
                },
            )

        # Final yield: (content, tool_results, usage_info, all_messages) for server processing
        yield (full_response, tool_results, usage_info, all_messages)

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
        conversation_id: str | None = None,
        is_sports: bool = False,
        sports_context: dict[str, Any] | None = None,
        is_language: bool = False,
        language_context: dict[str, Any] | None = None,
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
            - {"type": "final", "content": "...", "tool_results": [...], "usage_info": {...}, "result_messages": [...]}
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
            is_sports=is_sports,
            sports_context=sports_context,
            is_language=is_language,
            language_context=language_context,
        )

        # Accumulate full response text
        full_response = ""
        # Capture tool results for server-side extraction
        tool_results: list[dict[str, Any]] = []
        # Collect all messages for metadata tool arg extraction
        all_messages: list[BaseMessage] = list(messages)
        # Track token counts
        total_input_tokens = 0
        total_output_tokens = 0
        total_cached_tokens = 0
        chunk_count = 0
        # Track active tool calls by tool_call_id (NOT name: two parallel calls
        # to the same tool must emit separate tool_start/tool_end events)
        pending_tool_calls: set[str] = set()
        # Accumulate thinking text across chunks
        accumulated_thinking = ""
        # Track token yields for debugging
        token_yield_count = 0
        # Track if we're inside an echoed MSG_CONTEXT block (spans multiple chunks)
        in_msg_context = False
        # Carryover buffer for cross-chunk boundary marker detection
        carryover = ""
        end_marker = "-->"

        # Stream the graph execution with messages mode for token-level streaming
        # Wrapped in try-except to handle executor shutdown gracefully
        from src.agent.graph import get_graph_config

        config = get_graph_config()
        try:
            for event in self.graph.stream(
                cast(Any, {"messages": messages}),
                config=config,
                stream_mode="messages",
            ):
                # Guard clause: a non-tuple event must not fall through to the
                # processing below with an unbound/stale message_chunk
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
                    # Signal tool execution ended (matched by call id)
                    tool_call_id = getattr(message_chunk, "tool_call_id", None)
                    tool_name = getattr(message_chunk, "name", None)
                    if tool_call_id and tool_call_id in pending_tool_calls:
                        pending_tool_calls.discard(tool_call_id)
                        if tool_name:
                            yield {"type": "tool_end", "tool": tool_name}
                    continue

                # Process AI message chunks
                if isinstance(message_chunk, AIMessageChunk):
                    # Extract usage metadata immediately
                    chunk_count += 1
                    if hasattr(message_chunk, "usage_metadata") and message_chunk.usage_metadata:
                        usage = message_chunk.usage_metadata
                        if isinstance(usage, dict):
                            input_tokens, output_tokens, cache_read = _usage_tokens(usage)
                            if input_tokens > 0 or output_tokens > 0:
                                total_input_tokens += input_tokens
                                total_output_tokens += output_tokens
                                total_cached_tokens += cache_read

                    # Filter out non-chat node output (plan classifier, plan generation)
                    if source_node and source_node != CHAT_NODE_NAME:
                        continue

                    # Collect AIMessage chunks for metadata extraction (chat node only)
                    all_messages.append(message_chunk)

                    # Check for tool calls starting
                    if message_chunk.tool_calls or message_chunk.tool_call_chunks:
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
                                if chunk_id and chunk_name and chunk_id not in pending_tool_calls:
                                    pending_tool_calls.add(chunk_id)
                                    tool_start_event: dict[str, Any] = {
                                        "type": "tool_start",
                                        "tool": chunk_name,
                                    }
                                    if chunk_name in TOOL_METADATA:
                                        tool_start_event["metadata"] = TOOL_METADATA[chunk_name]
                                    yield tool_start_event
                            continue

                        for tc_id, tool_name, tool_args in tool_infos:
                            if tc_id not in pending_tool_calls:
                                pending_tool_calls.add(tc_id)
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
                            accumulated_thinking += thinking
                            yield {"type": "thinking", "text": accumulated_thinking}

                        # Process regular text content
                        if text_content:
                            # Handle echoed MSG_CONTEXT (history context) - may span multiple chunks
                            msg_context_marker = "<!-- MSG_CONTEXT:"

                            # Prepend any carryover from previous chunk for marker detection
                            if carryover:
                                text_content = carryover + text_content
                                carryover = ""

                            # Check if we're currently inside a MSG_CONTEXT block
                            if in_msg_context:
                                if end_marker in text_content:
                                    # Block ended - extract content after it
                                    end_pos = text_content.find(end_marker)
                                    text_content = text_content[end_pos + 3 :].lstrip()
                                    in_msg_context = False
                                    logger.info("MSG_CONTEXT block ended (multi-chunk)")
                                    if not text_content:
                                        continue
                                else:
                                    # Still inside MSG_CONTEXT block - check for partial end marker
                                    for i in range(len(end_marker) - 1, 0, -1):
                                        if text_content.endswith(end_marker[:i]):
                                            carryover = end_marker[:i]
                                            break
                                    continue

                            # Check if MSG_CONTEXT starts in this chunk
                            if msg_context_marker in text_content:
                                marker_pos = text_content.find(msg_context_marker)
                                # Check if block completes in this chunk
                                end_pos = text_content.find(end_marker, marker_pos)
                                if end_pos != -1:
                                    # Complete block in one chunk - strip it
                                    before = text_content[:marker_pos]
                                    after = text_content[end_pos + 3 :]
                                    text_content = (before + after).strip()
                                    logger.info(
                                        "Stripped echoed MSG_CONTEXT from output",
                                        extra={"remaining_len": len(text_content)},
                                    )
                                else:
                                    # Block starts but doesn't end - check for partial end marker
                                    content_after_marker = text_content[marker_pos:]
                                    for i in range(len(end_marker) - 1, 0, -1):
                                        if content_after_marker.endswith(end_marker[:i]):
                                            carryover = end_marker[:i]
                                            break
                                    text_content = text_content[:marker_pos].rstrip()
                                    in_msg_context = True
                                    logger.info("MSG_CONTEXT block started (will span chunks)")
                                if not text_content:
                                    continue
                            elif not in_msg_context:
                                # Check if MSG_CONTEXT marker might be split at chunk boundary
                                for i in range(len(msg_context_marker) - 1, 0, -1):
                                    partial = msg_context_marker[:i]
                                    if text_content.endswith(partial):
                                        carryover = partial
                                        text_content = text_content[:-i]
                                        break

                            # Add to full response and yield token
                            full_response += text_content
                            if text_content:
                                token_yield_count += 1
                                yield {"type": "token", "text": text_content}
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

        # Handle any remaining carryover (wasn't part of a marker)
        if carryover and not in_msg_context:
            full_response += carryover
            token_yield_count += 1
            yield {"type": "token", "text": carryover}

        # Apply tool call JSON cleanup to the full response
        clean_content = clean_tool_call_json(full_response)

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

        tool_rounds, tool_call_count = _tool_telemetry(all_messages)
        usage_info = {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "cached_input_tokens": total_cached_tokens,
            "tool_rounds": tool_rounds,
            "tool_call_count": tool_call_count,
        }

        # Final yield with all accumulated data
        yield {
            "type": "final",
            "content": clean_content,
            "tool_results": tool_results,
            "usage_info": usage_info,
            "result_messages": all_messages,
        }


def generate_title(user_message: str, assistant_response: str) -> str | None:
    """
    Generate a concise title for a conversation using Gemini.

    Args:
        user_message: The first user message
        assistant_response: The assistant's response

    Returns:
        A short, descriptive title (max ~50 chars), or None if generation
        failed. Callers should leave the existing title untouched on None so
        it can be retried opportunistically on the next user message.
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
The title MUST start with a single relevant emoji followed by a space.
The title should capture the main topic or intent.
Write the title in the same language the user writes in.
Do NOT use quotes around the title.
Do NOT include prefixes like "Title:" or "Topic:".
Just output the emoji and title text directly.

Example format: 🐍 Python List Sorting

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
        final_title = title or f"💬 {user_message[: Config.TITLE_FALLBACK_LENGTH]}"
        logger.debug("Title generated", extra={"title": final_title})
        return final_title
    except Exception as e:
        # Catch broadly: provider SDKs wrap errors in their own exception types
        # (e.g. ChatGoogleGenerativeAIError on 429), and title generation must
        # never break the surrounding message-save flow. Returning None tells
        # the caller to leave the default title in place so the next user
        # message will retry opportunistically.
        logger.warning(
            "Title generation failed",
            extra={"error": str(e), "error_type": type(e).__name__},
        )
        return None
