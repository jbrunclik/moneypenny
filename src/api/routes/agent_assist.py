"""Agent AI-assist routes: natural-language schedule parsing, prompt enhancer."""

from __future__ import annotations

from typing import Any

from src.agent.content import extract_text_content
from src.agent.tools.google_calendar import is_google_calendar_available
from src.agent.tools.todoist import is_todoist_available
from src.agent.tools.whatsapp import is_whatsapp_available
from src.api.rate_limiting import rate_limit_conversations
from src.api.routes.agents import api
from src.api.schemas.agents import (
    EnhancePromptRequest,
    EnhancePromptResponse,
    ParseScheduleRequest,
    ParseScheduleResponse,
)
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User
from src.utils.logging import get_logger

logger = get_logger(__name__)


_PROMPT_TOOL_DESCRIPTIONS: dict[str, str] = {
    "web_search": "Search the open web for current information, news, stats, and references.",
    "fetch_url": "Download the raw content of a specific URL (articles, docs, JSON) for analysis.",
    "retrieve_file": "Read files that the user previously uploaded in this conversation.",
    "generate_image": "Create or edit images through Gemini based on detailed prompts or references.",
    "execute_code": "Run short Python code in an isolated sandbox for data wrangling or calculations.",
    "request_approval": "Pause execution and ask the user for approval before sensitive work.",
    "trigger_agent": "Trigger another autonomous agent and optionally pass along instructions.",
    "todoist": "Create, update, and organize Todoist tasks, sections, and projects.",
    "google_calendar": "Read or modify Google Calendar events, attendees, and reminders.",
    "whatsapp": "Send WhatsApp notifications to the user with concise summaries and links.",
    "kv_store": "Persist and retrieve key-value data across conversations and executions.",
    "load_skill": "Load detailed built-in instructions for a specific kind of task (office files, PDFs, browser tactics, weekly planning, trips, shopping).",
}

_PROMPT_BASE_TOOL_ORDER = [
    "web_search",
    "fetch_url",
    "retrieve_file",
    "generate_image",
    "execute_code",
    "request_approval",
    "trigger_agent",
]


def _is_todoist_connected_for_user(user: User) -> bool:
    """Return True if Todoist is configured at app level AND connected for this user."""
    return bool(is_todoist_available() and user.todoist_access_token)


def _is_calendar_connected_for_user(user: User) -> bool:
    """Return True if Google Calendar is configured at app level AND connected for this user."""
    return bool(is_google_calendar_available() and user.google_calendar_access_token)


def _is_whatsapp_enabled_for_user(user: User) -> bool:
    """Return True if WhatsApp is configured at app level AND user has set their phone."""
    return bool(is_whatsapp_available() and user.whatsapp_phone)


def _resolve_requested_tools(user: User, tool_permissions: list[str] | None) -> list[str]:
    """Resolve optional tools based on explicit permissions or available integrations.

    When tool_permissions is None, auto-detect based on user's actual connections.
    When tool_permissions is provided, return them (filtering will happen in maybe_add).
    """
    if tool_permissions is None:
        # Auto-detect based on user's actual connections (not just app config)
        tools: list[str] = []
        if _is_todoist_connected_for_user(user):
            tools.append("todoist")
        if _is_calendar_connected_for_user(user):
            tools.append("google_calendar")
        if _is_whatsapp_enabled_for_user(user):
            tools.append("whatsapp")
        return tools

    # Filter duplicates while preserving order
    seen: set[str] = set()
    filtered: list[str] = []
    for tool in tool_permissions:
        if tool not in seen:
            filtered.append(tool)
            seen.add(tool)
    return filtered


def _format_tool_prompt_section(user: User, tool_permissions: list[str] | None) -> str:
    """Build a bullet list describing the tools available to the agent.

    Only includes tools that are:
    1. Available at app level (config/env vars set)
    2. Connected for this specific user (for integration tools)
    """
    added: set[str] = set()
    lines: list[str] = []

    def maybe_add(tool_name: str) -> None:
        if tool_name in added:
            return
        description = _PROMPT_TOOL_DESCRIPTIONS.get(tool_name)
        if not description:
            return

        # Respect runtime availability (app-level config)
        if tool_name == "execute_code" and not Config.CODE_SANDBOX_ENABLED:
            return
        if tool_name == "generate_image" and not Config.GEMINI_API_KEY:
            return

        # Check user-level connections for integration tools
        if tool_name == "todoist" and not _is_todoist_connected_for_user(user):
            return
        if tool_name == "google_calendar" and not _is_calendar_connected_for_user(user):
            return
        if tool_name == "whatsapp" and not _is_whatsapp_enabled_for_user(user):
            return

        lines.append(f"- {tool_name}: {description}")
        added.add(tool_name)

    for base_tool in _PROMPT_BASE_TOOL_ORDER:
        maybe_add(base_tool)

    for tool in _resolve_requested_tools(user, tool_permissions):
        maybe_add(tool)

    # Include any additional tools from the request that are not in the preferred order
    if tool_permissions:
        for tool in tool_permissions:
            maybe_add(tool)

    return "\n".join(lines)


@api.route("/ai-assist/parse-schedule", methods=["POST"])
@api.input(ParseScheduleRequest)
@api.output(ParseScheduleResponse)
@api.doc(responses=[400, 401])
@rate_limit_conversations
@require_auth
def parse_schedule(user: User, json_data: ParseScheduleRequest) -> dict[str, Any]:
    """Parse natural language schedule description into cron expression.

    Uses an LLM to convert user-friendly schedule descriptions
    (e.g., "every weekday at 9am") into standard cron expressions.
    """
    import json
    import re

    from langchain_core.messages import HumanMessage
    from langchain_google_genai import ChatGoogleGenerativeAI

    logger.info(
        "Parsing schedule",
        extra={"user_id": user.id, "input": json_data.natural_language[:100]},
    )

    try:
        # Use direct LLM call without system prompt overhead
        # This is a simple task that doesn't need tools or memory
        model = ChatGoogleGenerativeAI(
            model=Config.DEFAULT_MODEL,
            google_api_key=Config.GEMINI_API_KEY,
            temperature=0.1,  # Low temperature for consistent parsing
        )

        prompt = f"""Convert this natural language schedule description to a cron expression.

Schedule: "{json_data.natural_language}"
Timezone context: {json_data.timezone}

Respond with ONLY a JSON object in this exact format:
{{"cron": "<5-part cron expression>", "explanation": "<human readable description>"}}

For example:
- "every day at 9am" -> {{"cron": "0 9 * * *", "explanation": "Every day at 9:00 AM"}}
- "weekdays at 8:30am" -> {{"cron": "30 8 * * 1-5", "explanation": "Monday through Friday at 8:30 AM"}}
- "first monday of month at noon" -> {{"cron": "0 12 1-7 * 1", "explanation": "First Monday of each month at 12:00 PM"}}

Use standard 5-part cron format: minute hour day-of-month month day-of-week"""

        response = model.invoke([HumanMessage(content=prompt)])
        response_text = extract_text_content(response.content)

        # Extract JSON from response (handle potential markdown code blocks)
        json_match = re.search(r"\{[^{}]*\}", response_text)
        if json_match:
            result = json.loads(json_match.group())
            cron = result.get("cron")
            explanation = result.get("explanation")

            # Validate the cron expression
            if cron:
                from croniter import croniter

                try:
                    croniter(cron)
                    return {"cron": cron, "explanation": explanation, "error": None}
                except Exception:
                    return {
                        "cron": None,
                        "explanation": None,
                        "error": "Generated invalid cron expression",
                    }

        return {"cron": None, "explanation": None, "error": "Could not parse schedule"}

    except Exception as e:
        logger.warning(f"Schedule parsing failed: {e}", exc_info=True)
        return {"cron": None, "explanation": None, "error": str(e)}


@api.route("/ai-assist/enhance-prompt", methods=["POST"])
@api.input(EnhancePromptRequest)
@api.output(EnhancePromptResponse)
@api.doc(responses=[400, 401])
@rate_limit_conversations
@require_auth
def enhance_prompt(user: User, json_data: EnhancePromptRequest) -> dict[str, Any]:
    """Enhance an agent's system prompt using AI.

    Takes the current prompt and agent context, then suggests
    improvements for clarity, completeness, and effectiveness.
    """
    from langchain_core.messages import HumanMessage
    from langchain_google_genai import ChatGoogleGenerativeAI

    logger.info(
        "Enhancing prompt",
        extra={"user_id": user.id, "agent_name": json_data.agent_name},
    )

    try:
        import json

        # Use direct LLM call without system prompt overhead
        # This is a simple task that doesn't need tools or memory
        model = ChatGoogleGenerativeAI(
            model=Config.DEFAULT_MODEL,
            google_api_key=Config.GEMINI_API_KEY,
            temperature=0.7,  # Moderate temperature for creative improvement
        )

        tool_section = _format_tool_prompt_section(user, json_data.tool_permissions)
        tool_section_text = (
            f"\nTools available to this agent:\n{tool_section}\n\nInclude guidance on how the agent should use these tools when relevant.\n"
            if tool_section
            else ""
        )

        prompt = f"""Improve this autonomous agent's system prompt to be clearer and more effective.

Agent name: {json_data.agent_name}

Current prompt:
---
{json_data.prompt}
---
{tool_section_text}
Provide an enhanced version that:
1. Has clear, actionable goals
2. Specifies any constraints or limitations
3. Defines success criteria where appropriate
4. Uses concise, direct language
5. Reflects how the agent should leverage the tools listed above when applicable

Respond with ONLY a JSON object in this exact format:
{{"enhanced_prompt": "<the improved prompt text>", "error": null}}

If the prompt cannot be improved (too vague, empty, or inappropriate), return:
{{"enhanced_prompt": null, "error": "<explanation of the issue>"}}"""

        response = model.invoke([HumanMessage(content=prompt)])
        response_text = extract_text_content(response.content)

        # Clean up response - remove markdown code blocks if present
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # Parse JSON response
        try:
            result = json.loads(text)
            enhanced = result.get("enhanced_prompt")
            error = result.get("error")

            if error:
                return {"enhanced_prompt": None, "error": error}
            if enhanced:
                return {"enhanced_prompt": enhanced, "error": None}
        except json.JSONDecodeError:
            # If JSON parsing fails, the response might be plain text
            # Use it as the enhanced prompt
            if text and not text.startswith("{"):
                return {"enhanced_prompt": text, "error": None}

        return {"enhanced_prompt": None, "error": "Could not enhance prompt"}

    except Exception as e:
        logger.warning(f"Prompt enhancement failed: {e}", exc_info=True)
        return {"enhanced_prompt": None, "error": str(e)}
