"""The chat graph's state schema and node names, shared by every node."""

from typing import Annotated, NotRequired, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State for the chat agent."""

    messages: Annotated[list[BaseMessage], add_messages]
    tool_retries: int  # Consecutive tool failure count
    tool_rounds: int  # Tool-execution rounds this turn (round-multiplication cap)
    # Set once the turn's model was down and the other tier took over
    model_fallback: NotRequired[str]


# Node name used to filter streaming output — only chunks from this node are sent to frontend
CHAT_NODE_NAME = "chat"
