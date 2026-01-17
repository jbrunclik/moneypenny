"""Request approval tool for autonomous agents.

This tool allows agents to request user approval before performing
sensitive or potentially dangerous actions.
"""

from langchain_core.tools import tool

from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)


def build_approval_message(approval_id: str, description: str, tool_name: str = "") -> str:
    """Build the approval request message for the conversation.

    This is used by both the executor (batch mode) and streaming handler
    to create a consistent approval message format.

    Args:
        approval_id: The approval request ID
        description: Description of the action requiring approval
        tool_name: Name of the tool/integration requiring approval

    Returns:
        Formatted approval message with parseable marker
    """
    tool_line = f"\n\nTool: `{tool_name}`" if tool_name else ""
    return (
        f"[approval-request:{approval_id}]\n"
        f"**Action requires approval**\n\n"
        f"I need your permission to: **{description}**{tool_line}\n\n"
        f"Please approve or reject this request."
    )


class ApprovalRequestedException(Exception):
    """Raised when an agent requests approval.

    This exception signals the executor to pause and wait for user approval.
    """

    def __init__(self, approval_id: str, description: str, tool_name: str = ""):
        self.approval_id = approval_id
        self.description = description
        self.tool_name = tool_name
        super().__init__(f"Approval requested: {description}")


@tool
def request_approval(action_description: str, tool_name: str = "custom_action") -> str:
    """Request user approval before performing a sensitive action.

    Use this tool when you are about to perform an action that:
    - Is destructive or irreversible (deleting data, removing access)
    - Affects other users (sending messages, sharing content)
    - Posts content externally (social media, emails, public APIs)
    - Involves financial transactions or commitments
    - Could have significant real-world consequences

    After calling this tool, you MUST stop and wait. Do not proceed with the action
    until you receive confirmation that the user has approved it.

    Args:
        action_description: Clear description of what you want to do and why.
            Be specific about what will happen if approved.
            Example: "Send email to team@company.com about the project deadline"
        tool_name: The name of the tool/action category (e.g., "email", "todoist", "calendar")

    Returns:
        A message indicating that approval has been requested and the agent should wait.
    """
    # Lazy import to avoid circular dependency
    from src.agent.executor import get_agent_context

    # Get the current agent context
    agent_context = get_agent_context()

    if not agent_context:
        return (
            "Error: request_approval can only be used by autonomous agents. "
            "In interactive mode, simply ask the user directly."
        )

    agent = agent_context.agent
    user_id = agent_context.user.id

    logger.info(
        "Agent requesting approval",
        extra={
            "agent_id": agent.id,
            "agent_name": agent.name,
            "action": action_description,
            "tool": tool_name,
        },
    )

    # Create the approval request in the database
    approval = db.create_approval_request(
        agent_id=agent.id,
        user_id=user_id,
        tool_name=tool_name,
        tool_args={"description": action_description},
        description=action_description,
    )

    # Raise exception to pause execution
    # The executor will catch this and handle the approval flow
    raise ApprovalRequestedException(approval.id, action_description)
