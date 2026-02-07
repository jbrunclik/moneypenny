"""Agent executor module for running autonomous agents.

This module handles the actual execution of autonomous agents,
including creating messages and invoking the ChatAgent.
"""

from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.agent.agent import ChatAgent
from src.agent.content import (
    detect_response_language,
    extract_image_prompts_from_messages,
    extract_metadata_tool_args,
    extract_sources_fallback_from_tool_results,
)
from src.agent.tool_results import get_full_tool_results, set_current_request_id
from src.agent.tools import (
    get_tools_for_agent,
    set_agent_name,
    set_conversation_context,
    set_current_message_files,
)
from src.agent.tools.request_approval import (
    ApprovalRequestedException,
    build_approval_message,
)
from src.api.schemas import MessageRole
from src.api.utils import (
    calculate_and_save_message_cost,
    process_memory_operations,
    validate_memory_operations,
)
from src.config import Config
from src.db.models import db
from src.utils.images import (
    extract_code_output_files_from_tool_results,
    extract_generated_images_from_tool_results,
)
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.db.models import Agent, User

logger = get_logger(__name__)


# ============ Exceptions ============


class AgentBlockedError(Exception):
    """Raised when an agent is blocked (e.g., waiting for approval)."""

    pass


# ============ Context Management ============


@dataclass
class AgentContext:
    """Context for the currently executing agent."""

    agent: Agent
    user: User
    trigger_chain: list[str]  # List of agent IDs in the trigger chain


# Context variable for the current agent execution
_agent_context: contextvars.ContextVar[AgentContext | None] = contextvars.ContextVar(
    "_agent_context", default=None
)


def get_agent_context() -> AgentContext | None:
    """Get the current agent execution context."""
    return _agent_context.get()


def set_agent_context(context: AgentContext | None) -> None:
    """Set the current agent execution context."""
    _agent_context.set(context)


def clear_agent_context() -> None:
    """Clear the current agent execution context."""
    _agent_context.set(None)


def get_trigger_chain() -> list[str]:
    """Get the current trigger chain (agent IDs)."""
    context = _agent_context.get()
    return context.trigger_chain if context else []


def add_to_trigger_chain(agent_id: str) -> contextvars.Token[AgentContext | None]:
    """Add an agent ID to the trigger chain.

    Returns a token that can be used to reset the context.
    """
    context = _agent_context.get()
    if context:
        # Create a new context with the extended chain
        new_context = AgentContext(
            agent=context.agent,
            user=context.user,
            trigger_chain=context.trigger_chain + [agent_id],
        )
    else:
        # Create a minimal context with just the trigger chain
        # This shouldn't normally happen, but handle it gracefully
        new_context = AgentContext(
            agent=None,  # type: ignore[arg-type]
            user=None,  # type: ignore[arg-type]
            trigger_chain=[agent_id],
        )
    return _agent_context.set(new_context)


# ============ Stub Classes ============


class AgentExecutor:
    """Agent executor class for agent-to-agent triggering.

    This is used by the trigger_agent tool to execute another agent
    from within an agent's execution context.
    """

    def __init__(
        self,
        agent: Agent,
        user: User,
        trigger_type: str,
        triggered_by_agent_id: str | None = None,
    ) -> None:
        self.agent = agent
        self.user = user
        self.trigger_type = trigger_type
        self.triggered_by_agent_id = triggered_by_agent_id

    def run(self, message: str = "Continue") -> Any:
        """Run the agent and return a result object.

        Note: The `message` parameter is currently unused. The trigger message
        is generated internally by `execute_agent()` based on `trigger_type`.
        """
        # Get current trigger chain to pass to child
        parent_chain = get_trigger_chain()

        # Create execution record
        execution = db.create_execution(
            agent_id=self.agent.id,
            trigger_type=self.trigger_type,
            triggered_by_agent_id=self.triggered_by_agent_id,
        )

        # Execute the agent with the parent's trigger chain
        result, error_message = execute_agent(
            self.agent,
            self.user,
            self.trigger_type,
            execution.id,
            parent_trigger_chain=parent_chain,
        )

        # Handle the different return values properly
        if result is True:
            db.update_execution(execution.id, status="completed")
        elif result == "waiting_approval":
            # Executor already set status to waiting_approval, don't override
            raise AgentBlockedError(f"Agent is waiting for approval: {error_message}")
        else:
            db.update_execution(execution.id, status="failed", error_message=error_message)
            raise AgentBlockedError(error_message or "Agent execution failed")

        # Return a simple result object
        @dataclass
        class ExecutionResult:
            status: str
            execution_id: str

        return ExecutionResult(status="completed", execution_id=execution.id)


# ============ Main Executor Function ============


def execute_agent(
    agent: Agent,
    user: User,
    trigger_type: str,
    execution_id: str,
    parent_trigger_chain: list[str] | None = None,
) -> tuple[bool | str, str | None]:
    """Execute an autonomous agent.

    This function:
    1. Creates a trigger message in the agent's conversation
    2. Invokes the ChatAgent with the autonomous agent prompt
    3. Saves the response to the conversation
    4. Updates the execution status

    Args:
        agent: The agent to execute
        user: The user who owns the agent
        trigger_type: How the agent was triggered (scheduled, manual, agent_trigger)
        execution_id: The execution record ID
        parent_trigger_chain: List of agent IDs from parent execution (for circular detection)

    Returns:
        Tuple of (success/status, error_message)
        - (True, None) on success
        - ("waiting_approval", description) when approval requested
        - (False, error_message) on failure
    """
    logger.info(
        "Executing agent",
        extra={
            "agent_id": agent.id,
            "agent_name": agent.name,
            "user_id": user.id,
            "trigger_type": trigger_type,
            "execution_id": execution_id,
        },
    )

    # Check if agent has a conversation
    if not agent.conversation_id:
        error_msg = f"Agent has no conversation: {agent.id}"
        logger.error(error_msg, extra={"agent_id": agent.id})
        return False, error_msg

    # Check budget limit before execution
    if db.is_agent_over_budget(agent.id, agent.budget_limit):
        daily_spent = db.get_agent_daily_spending(agent.id)
        error_msg = f"Agent exceeded daily budget limit (${agent.budget_limit:.2f}, spent: ${daily_spent:.2f})"
        logger.warning(
            "Agent over budget",
            extra={
                "agent_id": agent.id,
                "budget_limit": agent.budget_limit,
                "daily_spent": daily_spent,
            },
        )
        return False, error_msg

    # Check if conversation needs compaction
    from src.agent.compaction import compact_conversation

    try:
        compact_conversation(agent)
    except Exception as e:
        # Log but don't fail execution if compaction fails
        logger.warning(
            "Conversation compaction failed",
            extra={"agent_id": agent.id, "error": str(e)},
        )

    # Get the agent's conversation
    conv = db.get_conversation(agent.conversation_id, user.id)
    if not conv:
        error_msg = f"Agent conversation not found: {agent.conversation_id}"
        logger.error(error_msg, extra={"agent_id": agent.id})
        return False, error_msg

    # Build the trigger message based on trigger type
    now = datetime.now(UTC)
    trigger_messages = {
        "scheduled": f"[Scheduled run at {now.strftime('%Y-%m-%d %H:%M UTC')}]",
        "manual": f"[Manual trigger at {now.strftime('%Y-%m-%d %H:%M UTC')}]",
        "agent_trigger": f"[Triggered by another agent at {now.strftime('%Y-%m-%d %H:%M UTC')}]",
    }
    trigger_message = trigger_messages.get(trigger_type, f"[Triggered: {trigger_type}]")

    # Save trigger message
    logger.debug(
        "Saving trigger message",
        extra={"agent_id": agent.id, "conversation_id": conv.id},
    )
    db.add_message(conv.id, MessageRole.USER, trigger_message)

    # Get conversation history (excluding the just-added message)
    messages = db.get_messages(conv.id)
    history = [
        {"role": m.role.value, "content": m.content}
        for m in messages[:-1]  # Exclude the trigger message
    ]

    # Get tools for the agent (includes request_approval, trigger_agent, etc.)
    agent_tools = get_tools_for_agent(agent)
    agent_tool_names = [t.name for t in agent_tools]

    # Build agent context for the system prompt
    agent_context = {
        "name": agent.name,
        "description": agent.description,
        "schedule": agent.schedule,
        "timezone": agent.timezone,
        "goals": agent.system_prompt,
        "tools": agent_tool_names,  # Actual tools available, not just permissions
        "trigger_type": trigger_type,
    }

    try:
        # Generate a unique request ID for capturing full tool results
        request_id = str(uuid.uuid4())
        set_current_request_id(request_id)
        set_current_message_files(None)
        set_conversation_context(conv.id, user.id)
        set_agent_name(agent.name)  # For WhatsApp template messages

        # Set the agent context so permission checks know we're in autonomous mode
        # Include parent trigger chain to detect circular dependencies
        full_trigger_chain = (parent_trigger_chain or []) + [agent.id]
        agent_execution_context = AgentContext(
            agent=agent,
            user=user,
            trigger_chain=full_trigger_chain,
        )
        set_agent_context(agent_execution_context)

        # Create agent with autonomous mode and tools
        chat_agent = ChatAgent(
            model_name=agent.model,  # Use the agent's configured model
            anonymous_mode=False,
            is_planning=False,
            is_autonomous=True,
            agent_context=agent_context,
            tools=agent_tools,
        )

        # Run the agent with retry logic for transient failures
        from src.agent.retry import with_retry

        def run_chat() -> tuple[str, list[Any], dict[str, Any], list[Any]]:
            return chat_agent.chat_batch(
                text=trigger_message,
                files=None,
                history=history,
                force_tools=None,
                user_name=user.name,
                user_id=user.id,
                custom_instructions=user.custom_instructions,
                is_planning=False,
            )

        raw_response, tool_results, usage_info, result_messages = with_retry(run_chat)()

        # Get full tool results
        full_tool_results = get_full_tool_results(request_id)
        set_current_request_id(None)
        set_current_message_files(None)
        set_conversation_context(None, None)
        set_agent_name(None)  # Clear agent name context

        logger.debug(
            "Agent execution completed",
            extra={
                "agent_id": agent.id,
                "response_length": len(raw_response),
                "tool_results_count": len(tool_results),
                "input_tokens": usage_info.get("input_tokens", 0),
                "output_tokens": usage_info.get("output_tokens", 0),
            },
        )

        # Extract metadata from tool calls and deterministic analysis
        clean_response = raw_response
        sources, memory_ops = extract_metadata_tool_args(result_messages)
        generated_images_meta = extract_image_prompts_from_messages(result_messages)
        language = detect_response_language(clean_response)

        # Fallback: if web_search was used but no cite_sources, extract from tool results
        if not sources and tool_results:
            sources = extract_sources_fallback_from_tool_results(tool_results)

        # Process memory operations
        memory_ops = validate_memory_operations(memory_ops)
        if memory_ops:
            logger.debug(
                "Processing memory operations from agent",
                extra={"agent_id": agent.id, "operation_count": len(memory_ops)},
            )
            process_memory_operations(user.id, memory_ops)

        # Extract generated files from tool results
        gen_image_files = extract_generated_images_from_tool_results(full_tool_results)
        code_output_files = extract_code_output_files_from_tool_results(full_tool_results)
        all_generated_files = gen_image_files + code_output_files

        # Ensure we have at least some content
        if not clean_response and all_generated_files:
            clean_response = Config.DEFAULT_IMAGE_GENERATION_MESSAGE

        # Save assistant message
        logger.debug(
            "Saving agent response",
            extra={"agent_id": agent.id, "conversation_id": conv.id},
        )
        assistant_msg = db.add_message(
            conv.id,
            MessageRole.ASSISTANT,
            clean_response,
            files=all_generated_files if all_generated_files else None,
            sources=sources if sources else None,
            generated_images=generated_images_meta if generated_images_meta else None,
            language=language,
        )

        # Calculate and save cost (mode="agent" for analytics distinction)
        calculate_and_save_message_cost(
            assistant_msg.id,
            conv.id,
            user.id,
            conv.model,
            usage_info,
            full_tool_results,
            len(clean_response),
            mode="agent",
        )

        # Update agent's last_run_at
        db.update_agent_last_run(agent.id)

        # Clean up context after successful execution
        set_current_request_id(None)
        set_current_message_files(None)
        set_conversation_context(None, None)
        set_agent_name(None)
        clear_agent_context()

        logger.info(
            "Agent execution successful",
            extra={
                "agent_id": agent.id,
                "execution_id": execution_id,
                "message_id": assistant_msg.id,
                "response_length": len(clean_response),
            },
        )

        return True, None

    except ApprovalRequestedException as e:
        # Agent used request_approval tool - waiting for user approval
        logger.info(
            "Agent requesting approval",
            extra={
                "agent_id": agent.id,
                "execution_id": execution_id,
                "approval_id": e.approval_id,
                "description": e.description,
            },
        )

        # Update execution status to waiting_approval
        db.update_execution(execution_id, status="waiting_approval")

        # Add a message to the conversation indicating approval is needed
        # Include approval ID in a parseable format for interactive UI
        approval_message = build_approval_message(e.approval_id, e.description, e.tool_name)
        db.add_message(conv.id, MessageRole.ASSISTANT, approval_message)

        # Clean up context
        set_current_request_id(None)
        set_current_message_files(None)
        set_conversation_context(None, None)
        set_agent_name(None)
        clear_agent_context()

        # Return special status to indicate approval is required
        # The calling code should NOT override the execution status
        return "waiting_approval", e.description

    except Exception as e:
        logger.error(
            "Agent execution failed",
            extra={
                "agent_id": agent.id,
                "execution_id": execution_id,
                "error": str(e),
            },
            exc_info=True,
        )
        # Clean up context
        set_current_request_id(None)
        set_current_message_files(None)
        set_conversation_context(None, None)
        set_agent_name(None)
        clear_agent_context()

        return False, str(e)
