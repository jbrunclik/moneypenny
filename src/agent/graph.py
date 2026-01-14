"""LangGraph chat graph construction for the chat agent.

This module handles creating and configuring the LangGraph state machine
that powers the chat agent's conversation flow with tool support.
"""

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode as BaseToolNode

from src.agent.content import strip_full_result_from_tool_content
from src.agent.tool_results import get_current_request_id, store_tool_result
from src.agent.tools import TOOLS
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


# ============ Agent State ============


class AgentState(TypedDict):
    """State for the chat agent."""

    messages: Annotated[list[BaseMessage], add_messages]


# ============ Model Creation ============


def create_chat_model(
    model_name: str,
    with_tools: bool = True,
    include_thoughts: bool = False,
    tools: list[Any] | None = None,
) -> ChatGoogleGenerativeAI:
    """Create a Gemini chat model, optionally with tools bound.

    Args:
        model_name: The Gemini model to use
        with_tools: Whether to bind tools to the model
        include_thoughts: Whether to include thinking/reasoning summaries in responses
        tools: Custom list of tools to bind (defaults to TOOLS if not provided)
    """
    model = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=Config.GEMINI_API_KEY,
        temperature=Config.GEMINI_DEFAULT_TEMPERATURE,
        convert_system_message_to_human=True,
        include_thoughts=include_thoughts,
    )

    active_tools = tools if tools is not None else TOOLS
    if with_tools and active_tools:
        return model.bind_tools(active_tools)  # type: ignore[return-value]

    return model


# ============ Graph Nodes ============


def should_continue(state: AgentState) -> Literal["tools", "end"]:
    """Decide whether to continue to tools or end the conversation."""
    messages = state["messages"]
    last_message = messages[-1]

    # If the last message has tool calls, continue to tools
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"

    return "end"


def chat_node(state: AgentState, model: ChatGoogleGenerativeAI) -> dict[str, list[BaseMessage]]:
    """Process messages and generate a response."""
    messages = state["messages"]
    message_count = len(messages)
    logger.debug(
        "Invoking LLM",
        extra={
            "message_count": message_count,
            "model": model.model_name if hasattr(model, "model_name") else "unknown",
        },
    )
    response = model.invoke(messages)

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

    return {"messages": [response]}


# ============ Tool Node Factory ============


def create_tool_node(tools: list[Any]) -> Any:
    """Create a tool node that strips large data from results before sending to LLM.

    This prevents the ~650K token cost of sending generated images back to the model.
    The full tool results are still captured separately for server-side extraction.

    The request ID is read from the _current_request_id contextvar at runtime,
    allowing per-request capture while using a single shared graph instance.

    Args:
        tools: List of tools to use
    """
    base_tool_node = BaseToolNode(tools)

    def tool_node_with_stripping(state: AgentState) -> dict[str, Any]:
        """Execute tools and strip _full_result from results."""
        logger.debug("tool_node_with_stripping starting")

        # Get the current request ID from contextvar
        request_id = get_current_request_id()

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
) -> StateGraph[AgentState]:
    """Create a chat graph with optional tool support.

    Args:
        model_name: The Gemini model to use
        with_tools: Whether to bind tools to the model
        include_thoughts: Whether to include thinking/reasoning summaries
        tools: Custom list of tools to use (defaults to TOOLS if not provided)
    """
    active_tools = tools if tools is not None else TOOLS
    model = create_chat_model(
        model_name, with_tools=with_tools, include_thoughts=include_thoughts, tools=active_tools
    )

    # Define the graph
    graph: StateGraph[AgentState] = StateGraph(AgentState)

    # Add the chat node
    graph.add_node("chat", lambda state: chat_node(state, model))

    if with_tools and active_tools:
        # Add tool node with stripping of large results
        tool_node = create_tool_node(active_tools)
        graph.add_node("tools", tool_node)

        # Set entry point
        graph.set_entry_point("chat")

        # Add conditional edge based on whether to use tools
        graph.add_conditional_edges("chat", should_continue, {"tools": "tools", "end": END})

        # After tools, go back to chat
        graph.add_edge("tools", "chat")
    else:
        # Simple graph without tools
        graph.set_entry_point("chat")
        graph.add_edge("chat", END)

    return graph
