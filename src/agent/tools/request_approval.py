"""Request approval tool for autonomous agents.

This tool allows agents to request user approval before performing
sensitive or potentially dangerous actions.
"""

from langchain_core.tools import tool

from src.agent.tools.errors import tool_error
from src.utils.logging import get_logger

logger = get_logger(__name__)

# edit_standing_chat files its own approvals (with the change as args); a
# request_approval under its name could pose as one
SETTINGS_TOOL = "edit_standing_chat"


def build_approval_message(
    description: str, tool_name: str = "", sibling_results: list[tuple[str, str]] | None = None
) -> str:
    """The run's waiting message; its card (the proposal) shows under it.

    sibling_results: (tool_name, result) pairs for tool calls from the same
    batch that already ran before the pause (R3) - recorded so the resumed
    run doesn't redo or forget that work.
    """
    tool_line = f"\n\nTool: `{tool_name}`" if tool_name else ""
    siblings_section = ""
    if sibling_results:
        lines = "\n".join(f"- `{name}`: {result}" for name, result in sibling_results)
        siblings_section = f"\n\nCompleted before pausing:\n{lines}"
    return f"**Waiting for your approval**\n\n{description}{tool_line}{siblings_section}"


class ApprovalRequestedException(Exception):  # noqa: N818 - control flow (pause for approval), not an error
    """Raised when an agent requests approval.

    This exception signals the executor to pause and wait for user approval.
    """

    def __init__(
        self, approval_id: str, description: str, tool_name: str = "", *, deferred: bool = False
    ):
        self.approval_id = approval_id
        self.description = description
        self.tool_name = tool_name
        # A gated call (run_approvals): the round's other calls still run and
        # the tool node pauses after it, on every card the round filed
        self.deferred = deferred
        # Filled by the tool node when sibling tool calls from the same batch
        # executed before the pause (R3)
        self.sibling_results: list[tuple[str, str]] = []
        super().__init__(f"Approval requested: {description}")


@tool
def request_approval(action_description: str, tool_name: str = "custom_action") -> str:
    """Ask the user's approval before an action no tool asks for itself -
    sending something on their behalf, posting content, spending money, or
    anything with real consequences. Changes in Todoist, Calendar, Garmin
    workouts and Rouvy need no call: when one needs the user's yes, the tool
    shows them that exact change and the run pauses by itself.

    After calling this tool, stop: the run pauses until the user answers and
    then resumes with their decision.

    Args:
        action_description: Exactly what you want to do and why, specific
            enough to decide on, e.g. "Send the weekly summary to Jana on WhatsApp".
        tool_name: The tool or action category it concerns (e.g. "whatsapp").
    """
    from src.agent.run_approvals import APPROVE_LABEL, KIND, file_run_card  # noqa: PLC0415 - cycle: run_approvals imports this module
    from src.agent.run_context import get_job_context  # noqa: PLC0415 - cycle: run_context imports this module

    job_context = get_job_context()
    if not job_context:
        return tool_error(
            "request_approval can only be used by autonomous agents. "
            "In interactive mode, simply ask the user directly.",
            retriable=False,
        )
    if tool_name == SETTINGS_TOOL:  # filed only by edit_standing_chat itself
        return tool_error("Use edit_standing_chat to propose a settings change.", retriable=False)
    logger.info(
        "Job run requesting approval",
        extra={"job_id": job_context.item.id, "tool": tool_name},
    )
    # Unbound: no call to match - it only pauses for the user's consent
    payload: dict[str, object] = {"tool": tool_name, "args": {}, "signature": None}
    card = file_run_card(
        job_context,
        KIND,
        action_description,
        {},
        [{"label": APPROVE_LABEL, "description": "", "payload": payload}],
    )
    raise ApprovalRequestedException(card.id, action_description, tool_name)
