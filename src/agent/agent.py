"""ChatAgent: runs one chat turn through the LangGraph agent graph.

Message content building lives in message_content.py, streamed output
translation in stream_events.py, usage/tool telemetry in turn_usage.py and
conversation title generation in title.py.
"""

import contextvars
import time
from collections.abc import Generator
from typing import Any, cast

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage

from src.agent.content import final_response_text
from src.agent.context_cache import CacheProfile
from src.agent.message_content import build_message_content, history_to_messages
from src.agent.prompts import get_system_prompt
from src.agent.stream_events import StreamEventProcessor, iter_token_stream
from src.agent.tools import get_tools_for_request
from src.agent.turn_usage import batch_usage_info
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
        is_sports: bool = False,
        sports_context: dict[str, Any] | None = None,
        is_language: bool = False,
        language_context: dict[str, Any] | None = None,
        enable_context_cache: bool = True,
        system_prompt_override: str | None = None,
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
        # A custom system prompt (delegate subagents) replaces the standard
        # prompt assembly entirely and forces uncached mode - the shared cache
        # profiles all embed the standard static prompt.
        self.system_prompt_override = system_prompt_override
        # Use provided tools, or get filtered tools based on mode
        if tools is not None:
            active_tools = tools
        elif is_autonomous and agent_context and "tools" in agent_context:
            # Interactive agent conversation - use agent's tool permissions
            # Note: tools=None means all tools, tools=[] means no extra integrations
            agent_tools = agent_context.get("tools")
            active_tools = get_tools_for_request(
                anonymous_mode, is_planning, agent_tool_permissions=agent_tools, is_agent=True
            )
        else:
            active_tools = get_tools_for_request(
                anonymous_mode, is_planning, is_sports=is_sports, is_language=is_language
            )

        # Determine cache profile and get cached content name
        self._cached_content_name: str | None = None
        if enable_context_cache and system_prompt_override is None:
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
        from src.agent.graph import get_compiled_graph

        # Memoized by build signature - the compiled graph is stateless and a
        # pure function of these args, so it is reused across requests instead
        # of recompiled on every ChatAgent construction (hot path).
        self.graph = get_compiled_graph(
            model_name,
            with_tools=with_tools,
            include_thoughts=include_thoughts,
            tools=active_tools,
            is_autonomous=is_autonomous,
            cached_content=self._cached_content_name,
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
        conversation_title: str | None = None,
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
        if self.system_prompt_override is not None:
            # Custom prompt (delegate subagents): used verbatim, no dynamic
            # context assembly
            messages.append(SystemMessage(content=self.system_prompt_override))
        elif self._cached_content_name:
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
                conversation_title=conversation_title,
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
                        conversation_title=conversation_title,
                    )
                )
            )

        if history:
            messages.extend(history_to_messages(history))

        # Append the deferred dynamic context (cached mode) right before the
        # current user message, keeping the volatile content at the tail.
        if dynamic_context_msg is not None:
            messages.append(dynamic_context_msg)

        # Add the current user message
        content = build_message_content(text, files)
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
        conversation_title: str | None = None,
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
            conversation_title=conversation_title,
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
        turn_started = time.monotonic()
        result = self.graph.invoke(cast(Any, {"messages": messages}), config=config)
        turn_duration_ms = round((time.monotonic() - turn_started) * 1000)
        result_messages: list[BaseMessage] = result["messages"]

        # Extract response (last AI message with actual content)
        response_text = final_response_text(result_messages)

        # Extract tool results
        tool_results: list[dict[str, Any]] = [
            {"type": "tool", "content": msg.content}
            for msg in result_messages
            if isinstance(msg, ToolMessage)
        ]

        if tool_results:
            logger.info("Tool results captured", extra={"tool_result_count": len(tool_results)})

        # Aggregate usage metadata from all AIMessages
        usage_info = batch_usage_info(result_messages, turn_duration_ms)

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
        conversation_title: str | None = None,
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
            conversation_title=conversation_title,
        )
        # Stream the graph execution with messages mode for token-level streaming
        from src.agent.graph import get_graph_config

        config = get_graph_config()
        turn_started = time.monotonic()
        yield from iter_token_stream(
            self.graph.stream(
                cast(Any, {"messages": messages}),
                config=config,
                stream_mode="messages",
            ),
            messages,
            turn_started,
        )

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
        conversation_title: str | None = None,
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
            conversation_title=conversation_title,
        )
        processor = StreamEventProcessor(messages)

        # Stream the graph execution with messages mode for token-level streaming
        # Wrapped in try-except to handle executor shutdown gracefully
        from src.agent.graph import get_graph_config

        config = get_graph_config()
        turn_started = time.monotonic()
        try:
            for mode, event in self.graph.stream(
                cast(Any, {"messages": messages}),
                config=config,
                # "custom" carries node-written statuses (transient-error
                # retries) that must reach the client while the node sleeps
                stream_mode=["messages", "custom"],
            ):
                yield from processor.process(mode, event)
        except RuntimeError as e:
            # Handle executor shutdown gracefully (e.g., during server restart)
            # Python's ThreadPoolExecutor raises generic RuntimeError with specific messages
            # when submit() is called after shutdown - there's no specific exception class
            error_msg = str(e).lower()
            if "cannot schedule new futures" in error_msg and "shutdown" in error_msg:
                logger.warning(
                    "Streaming interrupted by executor shutdown (likely server restart)",
                    extra={
                        "accumulated_response_length": len(processor.full_response),
                        "has_tool_results": bool(processor.tool_results),
                    },
                )
                # Continue to yield accumulated content and final event
            else:
                # Re-raise other RuntimeErrors
                raise

        yield from processor.finish(turn_started)
