"""Autonomous-agent section of the system prompt (split out of prompts.py, Sep 2026)."""

from src.agent.prompt_texts.agents import (
    AGENT_CONTEXT_FRESH,
    AGENT_CONTEXT_PERSISTENT,
    AUTONOMOUS_AGENT_SYSTEM_PROMPT,
)


def get_autonomous_agent_prompt(
    agent_name: str,
    agent_description: str | None,
    agent_schedule: str | None,
    agent_timezone: str,
    agent_goals: str | None,
    agent_tools: list[str],
    trigger_type: str,
    fresh_context: bool = False,
) -> str:
    """Build the autonomous agent section of the system prompt.

    Args:
        agent_name: The agent's name
        agent_description: The agent's description
        agent_schedule: The cron schedule string
        agent_timezone: The agent's timezone
        agent_goals: The agent's system prompt / goals
        agent_tools: List of permitted tool names
        trigger_type: How the agent was triggered (scheduled, manual, agent_trigger)

    Returns:
        Formatted autonomous agent prompt section
    """
    # Format schedule description
    if agent_schedule:
        schedule_desc = agent_schedule
    else:
        schedule_desc = "Manual trigger only"

    # Format tools description
    if agent_tools:
        tools_desc = "You have access to:\n" + "\n".join(f"- {tool}" for tool in agent_tools)
    else:
        tools_desc = "Basic tools only (web search, URL fetching, file retrieval)"

    # Format goals
    goals_desc = agent_goals if agent_goals else "Execute tasks as directed by the user."

    # Format trigger context
    trigger_context_map = {
        "scheduled": "Scheduled run (automatic)",
        "manual": "Manual trigger by user",
        "agent_trigger": "Triggered by another agent",
    }
    trigger_context = trigger_context_map.get(trigger_type, trigger_type)

    return AUTONOMOUS_AGENT_SYSTEM_PROMPT.format(
        agent_name=agent_name,
        agent_description=agent_description or "No description provided",
        agent_schedule=schedule_desc,
        agent_timezone=agent_timezone,
        agent_goals=goals_desc,
        agent_tools=tools_desc,
        # The section must match how the executor actually builds history,
        # otherwise the model is told to use context it doesn't have
        conversation_context=AGENT_CONTEXT_FRESH if fresh_context else AGENT_CONTEXT_PERSISTENT,
        trigger_context=trigger_context,
    )
