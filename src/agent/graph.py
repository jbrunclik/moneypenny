"""LangGraph chat graph construction for the chat agent.

This module handles creating and configuring the LangGraph state machine
that powers the chat agent's conversation flow with tool support.

Graph flow (with tools):
  START -> should_plan -> "plan": plan_node -> chat -> should_continue -> "tools": tools -> check_tool_results -> chat (loop)
                       -> "chat": chat -> should_continue -> ...                                                -> "end": END

Graph flow (without tools or planning disabled):
  START -> chat -> END
"""

import sqlite3
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode as BaseToolNode

from src.agent.content import extract_text_content, strip_full_result_from_tool_content
from src.agent.retry import with_retry
from src.agent.tool_results import get_current_request_id, store_tool_result
from src.agent.tools import TOOLS
from src.agent.tools.metadata import METADATA_TOOL_NAMES
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


# Import permission-related modules (at module level to avoid repeated imports)
# These are only used when is_autonomous=True
def _get_permission_modules() -> dict[str, Any]:
    """Lazy import of permission-related modules to avoid circular imports."""
    from src.agent.executor import get_agent_context
    from src.agent.permissions import PermissionResult, check_tool_permission

    return {
        "get_agent_context": get_agent_context,
        "check_tool_permission": check_tool_permission,
        "PermissionResult": PermissionResult,
    }


_checkpointer: SqliteSaver | None = None


def _get_checkpointer() -> SqliteSaver:
    """Lazily create a SqliteSaver backed by a file on disk.

    Each gunicorn worker (separate process) gets its own SQLite connection.
    WAL mode (set by SqliteSaver.setup()) enables concurrent reads.
    """
    global _checkpointer  # noqa: PLW0603
    if _checkpointer is None:
        db_path = Config.CHECKPOINT_DB_PATH
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
        )
        _checkpointer = SqliteSaver(conn)
        _checkpointer.setup()
        logger.info("SqliteSaver checkpointer initialized", extra={"path": str(db_path)})
    return _checkpointer


# ============ Agent State ============


class AgentState(TypedDict):
    """State for the chat agent."""

    messages: Annotated[list[BaseMessage], add_messages]
    tool_retries: int  # Consecutive tool failure count
    plan: str  # Execution plan for complex requests


# ============ Node & Planning Constants ============

# Node name used to filter streaming output — only chunks from this node are sent to frontend
CHAT_NODE_NAME = "chat"

PLANNING_PROMPT = (
    "Analyze the user's request and create a concise execution plan.\n"
    "- List 3-5 concrete steps you'll take\n"
    "- Mention which tools you'll use for each step\n"
    "- Keep it brief - this is an internal plan, not a response to the user"
)

PLANNING_DECISION_PROMPT = (
    "You are a routing classifier. Decide if the user's request requires multi-step "
    "planning (using multiple tools sequentially, combining results, or multi-part tasks) "
    "or can be handled directly.\n\n"
    "Reply with ONLY one word: PLAN or CHAT\n"
    "- PLAN: Complex requests needing 3+ steps, multiple tools, or multi-part work\n"
    "- CHAT: Simple questions, single-tool tasks, greetings, or short requests"
)


# ============ Model Creation ============


def create_chat_model(
    model_name: str,
    with_tools: bool = True,
    include_thoughts: bool = False,
    tools: list[Any] | None = None,
    temperature: float | None = None,
    cached_content: str | None = None,
) -> ChatGoogleGenerativeAI:
    """Create a Gemini chat model, optionally with tools bound.

    Args:
        model_name: The Gemini model to use
        with_tools: Whether to bind tools to the model
        include_thoughts: Whether to include thinking/reasoning summaries in responses
        tools: Custom list of tools to bind (defaults to TOOLS if not provided)
        temperature: Override for model temperature (defaults to Config.GEMINI_DEFAULT_TEMPERATURE)
        cached_content: Gemini cached content name. When provided, tools are NOT bound
            (they're already in the cache) and system_instruction is omitted.
    """
    kwargs: dict[str, Any] = {
        "model": model_name,
        "google_api_key": Config.GEMINI_API_KEY,
        "temperature": temperature
        if temperature is not None
        else Config.GEMINI_DEFAULT_TEMPERATURE,
        "convert_system_message_to_human": True,
        "include_thoughts": include_thoughts,
    }

    if cached_content:
        kwargs["cached_content"] = cached_content
        # Do NOT bind_tools when using cached_content — tools are in the cache
        logger.info(
            "Creating model with cached content",
            extra={"cached_content": cached_content, "model": model_name},
        )
        return ChatGoogleGenerativeAI(**kwargs)

    model = ChatGoogleGenerativeAI(**kwargs)

    active_tools = tools if tools is not None else TOOLS
    if with_tools and active_tools:
        return model.bind_tools(active_tools)  # type: ignore[return-value]

    return model


# ============ Graph Nodes ============


def should_continue(state: AgentState) -> Literal["tools", "end"]:
    """Decide whether to continue to tools or end the conversation.

    When all tool calls in the final message are metadata-only (cite_sources,
    manage_memory) AND the LLM already produced text, routes to "end" instead
    of "tools" to avoid an extra LLM round-trip. The tool call args are
    extracted from the AIMessage in post-processing.

    If the LLM produced metadata-only tool calls but NO text, routes to "tools"
    so the tools execute normally and the LLM gets another turn to respond with text.
    This prevents empty messages when e.g. manage_memory is the only output.
    """
    messages = state["messages"]
    last_message = messages[-1]

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        if all(tc["name"] in METADATA_TOOL_NAMES for tc in last_message.tool_calls):
            # If LLM already generated text alongside metadata tools,
            # skip execution - args are extracted in post-processing
            if extract_text_content(last_message.content).strip():
                return "end"
            # No text generated - execute tools so LLM gets another
            # turn to produce a text response
            return "tools"
        return "tools"

    return "end"


def should_plan(state: AgentState) -> Literal["plan", "chat"]:
    """Decide whether to run the planning node before chat.

    Uses a fast LLM call to classify whether the request needs planning.
    This is language-agnostic (works with Czech and any other language).
    Falls back to "chat" on any error.
    """
    if not Config.AGENT_PLANNING_ENABLED:
        return "chat"

    # Safety: don't re-plan if plan already exists
    if state.get("plan"):
        return "chat"

    # Find the latest HumanMessage
    messages = state["messages"]
    last_human = None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_human = msg
            break

    if not last_human:
        return "chat"

    content = last_human.content if isinstance(last_human.content, str) else str(last_human.content)

    # Short messages skip planning (fast path, no LLM call needed)
    if len(content) < Config.AGENT_PLANNING_MIN_LENGTH:
        return "chat"

    # Use fast LLM to decide (language-agnostic)
    try:
        classifier = ChatGoogleGenerativeAI(
            model=Config.AI_ASSIST_MODEL,
            google_api_key=Config.GEMINI_API_KEY,
            temperature=0.0,
        )

        response = classifier.invoke(
            [
                SystemMessage(content=PLANNING_DECISION_PROMPT),
                HumanMessage(content=content[:500]),  # Truncate to save tokens
            ]
        )
        decision = extract_text_content(response.content).strip().upper()

        if "PLAN" in decision and "CHAT" not in decision:
            logger.info(
                "Planning triggered by LLM classifier",
                extra={"content_length": len(content), "decision": decision},
            )
            return "plan"

        return "chat"
    except Exception:
        logger.debug("Planning classifier failed, falling back to chat", exc_info=True)
        return "chat"


def plan_node(state: AgentState, model_name: str) -> dict[str, str]:
    """Generate an execution plan for complex requests.

    Creates a separate model instance (no tools) to analyze the request
    and produce a concise plan. The plan is stored in state but not
    added to messages (invisible to the user).
    """
    planner = create_chat_model(model_name, with_tools=False, temperature=0.3)

    # Build minimal messages for planning: system prompt + user messages
    plan_messages: list[BaseMessage] = [SystemMessage(content=PLANNING_PROMPT)]
    for msg in state["messages"]:
        if isinstance(msg, (HumanMessage, SystemMessage)):
            plan_messages.append(msg)

    response = with_retry(planner.invoke)(plan_messages)
    plan_text = extract_text_content(response.content)

    logger.info("Plan generated", extra={"plan_length": len(plan_text)})
    return {"plan": plan_text}


def chat_node(
    state: AgentState,
    model: ChatGoogleGenerativeAI,
    use_cache: bool = False,
) -> dict[str, list[BaseMessage] | str]:
    """Process messages and generate a response.

    If a plan exists in state, it's injected for this invocation only,
    then cleared from state. When use_cache is True, uses HumanMessage
    instead of SystemMessage (LangChain silently drops mid-conversation
    SystemMessages when there's no SystemMessage at position 0).
    """
    messages = list(state["messages"])

    # Inject plan if present
    plan = state.get("plan", "")
    if plan:
        plan_message: HumanMessage | SystemMessage
        if use_cache:
            plan_message = HumanMessage(
                content=f"[SYSTEM GUIDANCE]\n[EXECUTION PLAN]\n{plan}\n[END PLAN]\n[/SYSTEM GUIDANCE]"
            )
        else:
            plan_message = SystemMessage(content=f"[EXECUTION PLAN]\n{plan}\n[END PLAN]")
        # Insert after the first SystemMessage (system prompt) or at start if cached
        insert_idx = 1
        if not use_cache:
            for i, msg in enumerate(messages):
                if isinstance(msg, SystemMessage):
                    insert_idx = i + 1
                    break
        messages.insert(insert_idx, plan_message)
        logger.debug("Injected plan into chat messages", extra={"plan_length": len(plan)})

    message_count = len(messages)
    logger.debug(
        "Invoking LLM",
        extra={
            "message_count": message_count,
            "model": model.model_name if hasattr(model, "model_name") else "unknown",
        },
    )
    response = with_retry(model.invoke)(messages)

    # Log tool calls if present
    if isinstance(response, AIMessage) and response.tool_calls:
        tool_names = [tc.get("name", "unknown") for tc in response.tool_calls]
        logger.info(
            "LLM requested tool calls",
            extra={"tool_calls": tool_names, "count": len(response.tool_calls)},
        )
    else:
        logger.debug("LLM response received", extra={"has_content": bool(response.content)})

    # Log usage metadata if available
    # Note: usage_metadata is a direct attribute, not in response_metadata
    if isinstance(response, AIMessage):
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage = response.usage_metadata
            logger.debug(
                "Usage metadata captured",
                extra={
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
            )
        else:
            logger.debug("No usage_metadata attribute found on AIMessage")

    result: dict[str, list[BaseMessage] | str] = {"messages": [response]}
    # Clear plan after first use
    if plan:
        result["plan"] = ""
    return result


def check_tool_results(
    state: AgentState,
    use_cache: bool = False,
) -> dict[str, Any]:
    """Inspect tool results and provide self-correction guidance if errors occurred.

    After tools execute, this node checks for errors:
    - If errors found and retries < max: increment retries, add correction guidance
    - If errors found and retries >= max: increment retries, add give-up guidance
    - If no errors: reset retries to 0
    Always routes back to "chat" - the LLM decides whether to retry or respond.

    When use_cache is True, guidance is sent as HumanMessage (not SystemMessage)
    because LangChain drops mid-conversation SystemMessages in cached mode.
    """
    messages = state["messages"]
    tool_retries = state.get("tool_retries", 0)
    max_retries = Config.AGENT_MAX_TOOL_RETRIES

    # Scan latest ToolMessages for errors
    has_error = False
    error_details: list[str] = []
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            # Check for explicit error status
            if getattr(msg, "status", None) == "error":
                has_error = True
                error_details.append(str(msg.content)[:200])
            # Check for error content patterns
            elif isinstance(msg.content, str) and (
                "Error:" in msg.content
                or "error:" in msg.content
                or "Exception:" in msg.content
                or "Traceback" in msg.content
                or "failed" in msg.content.lower()[:50]
            ):
                has_error = True
                error_details.append(msg.content[:200])
        elif isinstance(msg, AIMessage):
            # Stop scanning once we hit the AIMessage that triggered the tools
            break

    if not has_error:
        # No errors - reset retry counter
        if tool_retries > 0:
            logger.debug("Tool retries reset after successful execution")
        return {"tool_retries": 0}

    new_retries = tool_retries + 1
    error_summary = "; ".join(error_details[:3])

    # Use HumanMessage in cached mode (LangChain drops mid-conversation SystemMessages)
    GuidanceMessage = HumanMessage if use_cache else SystemMessage

    if new_retries <= max_retries:
        logger.info(
            "Tool error detected, providing self-correction guidance",
            extra={"retry": new_retries, "max_retries": max_retries, "errors": error_summary},
        )
        guidance_content = (
            "The tool call failed with the following error. "
            "Analyze the error and try a different approach or different arguments. "
            "Do not repeat the same failing call.\n\n"
            f"Error: {error_summary}"
        )
        if use_cache:
            guidance_content = f"[SYSTEM GUIDANCE]\n{guidance_content}\n[/SYSTEM GUIDANCE]"
        guidance = GuidanceMessage(content=guidance_content)
        return {"tool_retries": new_retries, "messages": [guidance]}
    else:
        logger.warning(
            "Tool error after max retries, providing give-up guidance",
            extra={"retry": new_retries, "max_retries": max_retries, "errors": error_summary},
        )
        guidance_content = (
            "The tool has failed after multiple retries. "
            "Respond to the user explaining what happened and offer alternatives. "
            "Do not attempt to call the same tool again."
        )
        if use_cache:
            guidance_content = f"[SYSTEM GUIDANCE]\n{guidance_content}\n[/SYSTEM GUIDANCE]"
        guidance = GuidanceMessage(content=guidance_content)
        return {"tool_retries": new_retries, "messages": [guidance]}


# ============ Tool Node Factory ============


def create_tool_node(tools: list[Any], is_autonomous: bool = False) -> Any:
    """Create a tool node that strips large data from results before sending to LLM.

    This prevents the ~650K token cost of sending generated images back to the model.
    The full tool results are still captured separately for server-side extraction.

    The request ID is read from the _current_request_id contextvar at runtime,
    allowing per-request capture while using a single shared graph instance.

    For autonomous agents (is_autonomous=True), this also checks tool permissions
    and may raise ApprovalRequiredException if a tool call requires user approval.

    Args:
        tools: List of tools to use
        is_autonomous: If True, check permissions and require approval for dangerous operations
    """
    base_tool_node = BaseToolNode(tools, handle_tool_errors=True)

    def tool_node_with_stripping(state: AgentState) -> dict[str, Any]:
        """Execute tools and strip _full_result from results."""
        logger.debug("tool_node_with_stripping starting", extra={"is_autonomous": is_autonomous})

        # Get the current request ID from contextvar
        request_id = get_current_request_id()

        # For autonomous agents, check if tools are blocked
        if is_autonomous:
            modules = _get_permission_modules()
            agent_context = modules["get_agent_context"]()

            if agent_context:
                # Get the last message which contains tool calls
                last_message = state["messages"][-1]
                if isinstance(last_message, AIMessage) and last_message.tool_calls:
                    for tool_call in last_message.tool_calls:
                        tool_name = tool_call.get("name")
                        tool_args = tool_call.get("args", {})

                        if not tool_name:
                            continue

                        # Check permission
                        permission = modules["check_tool_permission"](
                            agent_context.agent,
                            tool_name,
                            tool_args,
                        )

                        if permission == modules["PermissionResult"].BLOCKED:
                            # Return blocked message instead of executing
                            return {
                                "messages": [
                                    ToolMessage(
                                        content=f"Tool '{tool_name}' is not permitted for this agent",
                                        tool_call_id=tool_call.get("id", ""),
                                    )
                                ]
                            }

        # Call the base ToolNode
        result: dict[str, Any] = base_tool_node.invoke(state)

        # Capture full tool results BEFORE stripping, then strip for LLM
        if "messages" in result:
            for msg in result["messages"]:
                if isinstance(msg, ToolMessage) and isinstance(msg.content, str):
                    # Store the ORIGINAL content for server-side extraction
                    if request_id is not None:
                        store_tool_result(request_id, msg.content)

                    # Now strip _full_result for the LLM
                    content_len_before = len(msg.content)
                    msg.content = strip_full_result_from_tool_content(msg.content)
                    content_len_after = len(msg.content)
                    if content_len_before != content_len_after:
                        logger.info(
                            "Stripped _full_result from tool message",
                            extra={
                                "content_len_before": content_len_before,
                                "content_len_after": content_len_after,
                                "bytes_saved": content_len_before - content_len_after,
                            },
                        )

        logger.debug("tool_node_with_stripping completed")
        return result

    return tool_node_with_stripping


# ============ Graph Factory ============


def create_chat_graph(
    model_name: str,
    with_tools: bool = True,
    include_thoughts: bool = False,
    tools: list[Any] | None = None,
    is_autonomous: bool = False,
    cached_content: str | None = None,
) -> StateGraph[AgentState]:
    """Create a chat graph with optional tool support.

    The graph includes:
    - Planning node (optional, for complex multi-step requests)
    - Chat node (LLM invocation)
    - Tool node (with error handling and result stripping)
    - Self-correction node (inspects tool errors and guides retries)

    Args:
        model_name: The Gemini model to use
        with_tools: Whether to bind tools to the model
        include_thoughts: Whether to include thinking/reasoning summaries
        tools: Custom list of tools to use (defaults to TOOLS if not provided)
        is_autonomous: If True, check permissions and require approval for dangerous operations
        cached_content: Gemini cached content name (tools are in the cache, not bound)
    """
    active_tools = tools if tools is not None else TOOLS
    model = create_chat_model(
        model_name,
        with_tools=with_tools,
        include_thoughts=include_thoughts,
        tools=active_tools,
        cached_content=cached_content,
    )

    # Capture whether cache is active for nodes that inject guidance messages
    use_cache = cached_content is not None

    # Define the graph
    graph: StateGraph[AgentState] = StateGraph(AgentState)

    # Add the chat node
    graph.add_node("chat", lambda state: chat_node(state, model, use_cache=use_cache))

    if with_tools and active_tools:
        # Add tool node with stripping of large results and error handling
        tool_node = create_tool_node(active_tools, is_autonomous=is_autonomous)
        graph.add_node("tools", tool_node)

        # Add self-correction node
        graph.add_node(
            "check_tool_results",
            lambda state: check_tool_results(state, use_cache=use_cache),
        )

        # Add planning node
        graph.add_node("plan", lambda state: plan_node(state, model_name))

        # Entry point: conditional routing to plan or chat
        graph.add_conditional_edges(
            "__start__",
            should_plan,
            {"plan": "plan", "chat": "chat"},
        )

        # After planning, go to chat
        graph.add_edge("plan", "chat")

        # Add conditional edge based on whether to use tools
        graph.add_conditional_edges("chat", should_continue, {"tools": "tools", "end": END})

        # After tools, check results for errors
        graph.add_edge("tools", "check_tool_results")

        # After checking results, go back to chat
        graph.add_edge("check_tool_results", "chat")
    else:
        # Simple graph without tools
        graph.set_entry_point("chat")
        graph.add_edge("chat", END)

    return graph


def compile_graph(
    graph: StateGraph[AgentState],
    conversation_id: str | None = None,
) -> Any:
    """Compile a StateGraph with optional checkpointing.

    Args:
        graph: The StateGraph to compile
        conversation_id: Optional conversation ID for checkpointing thread

    Returns:
        Compiled graph ready for invoke/stream
    """
    if Config.AGENT_CHECKPOINTING_ENABLED:
        return graph.compile(checkpointer=_get_checkpointer())
    return graph.compile()


def get_graph_config(conversation_id: str | None = None) -> dict[str, Any]:
    """Build config dict for graph invoke/stream calls.

    Args:
        conversation_id: Optional conversation ID for checkpointing thread

    Returns:
        Config dict with thread_id for checkpointing
    """
    if Config.AGENT_CHECKPOINTING_ENABLED and conversation_id:
        return {"configurable": {"thread_id": conversation_id}, "recursion_limit": 25}
    return {"recursion_limit": 25}
