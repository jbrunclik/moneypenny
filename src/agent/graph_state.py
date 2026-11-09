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
    # The turn's budget (src/agent/turn_budget.py): clock, running cost,
    # failed-call signatures, the stop reason once a limit is hit, and
    # whether the one wrap-up notice went out
    turn_started_at: NotRequired[float]
    turn_cost_usd: NotRequired[float]
    failed_calls: NotRequired[dict[str, int]]
    final_answer: NotRequired[str]
    wrap_up_noticed: NotRequired[bool]
    # Loop detector (src/agent/tool_loops.py): the last rounds' signatures,
    # whether the A-B-A-B warning went out, and large results already seen
    recent_rounds: NotRequired[list[str]]
    ab_warned: NotRequired[bool]
    seen_results: NotRequired[dict[str, str]]


# Node name used to filter streaming output — only chunks from this node are sent to frontend
CHAT_NODE_NAME = "chat"
