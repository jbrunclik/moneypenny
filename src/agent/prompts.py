"""System prompts and user context for the chat agent.

This module contains all the system prompts, user context generation,
and memory-related prompt functions.
"""

import functools
import json
from datetime import datetime
from typing import Any

from src.agent.prompt_agents import get_autonomous_agent_prompt
from src.agent.prompt_dashboard import get_dashboard_context_prompt
from src.agent.prompt_memory import (
    get_memory_instructions_prompt,
    get_user_memories_list_prompt,
    get_user_memories_prompt,
)
from src.agent.prompt_programs import (
    PROGRAM_STATIC_KV_NOTE,
    PROGRAM_STATIC_PREAMBLE,
    format_language_kv_data,
    format_program_dynamic_context,
    format_sports_kv_data,
)
from src.agent.prompt_texts.core import (
    BASE_SYSTEM_PROMPT,
    CONVERSATION_TITLE_CONTEXT_PROMPT,
    CUSTOM_INSTRUCTIONS_PROMPT,
    TOOLS_SYSTEM_PROMPT_BASE,
    TOOLS_SYSTEM_PROMPT_CONTEXT,
    TOOLS_SYSTEM_PROMPT_PLACES,
)
from src.agent.prompt_texts.language import LANGUAGE_TUTOR_SYSTEM_PROMPT
from src.agent.prompt_texts.planner import PLANNER_SYSTEM_PROMPT
from src.agent.prompt_texts.productivity import TOOLS_SYSTEM_PROMPT_PRODUCTIVITY
from src.agent.prompt_texts.sports import SPORTS_TRAINER_SYSTEM_PROMPT
from src.agent.skills import skills_index_prompt
from src.agent.tools.context import get_location_context
from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger
from src.utils.mapy import MapyError, is_mapy_configured, mapy_rgeocode

logger = get_logger(__name__)


@functools.lru_cache(maxsize=256)
def _cached_locality(lon_r: float, lat_r: float) -> str | None:
    """Reverse geocode rounded coords -> short locality label (cached per worker)."""
    try:
        items = mapy_rgeocode(lon_r, lat_r)
    except MapyError as e:
        logger.warning("Reverse geocode failed", extra={"error": str(e)})
        return None
    if not items:
        return None
    return items[0].get("location") or items[0].get("name")


def _reverse_geocode_locality(lon: float, lat: float) -> str | None:
    """Locality label for coords, rounded to ~110 m so the cache and prompt stay stable."""
    if not is_mapy_configured():
        return None
    return _cached_locality(round(lon, 3), round(lat, 3))


def _get_saved_places_lines(user_id: str | None) -> list[str]:
    """Bullet lines for the user's saved places (kv_store namespace 'places')."""
    if not user_id:
        return []
    lines: list[str] = []
    for key, value in db.kv_list(user_id, "places"):
        try:
            address = json.loads(value).get("address", "")
        except json.JSONDecodeError, TypeError, AttributeError:
            address = ""
        lines.append(f"- {key}: {address}" if address else f"- {key}")
    return lines


# ============ Base System Prompt ============


# ============ Tools System Prompts ============


# ============ Planner System Prompt ============


# ============ Sports Trainer System Prompt ============


# ============ Language Tutor System Prompt ============


# ============ Autonomous Agent System Prompt ============


# ============ Custom Instructions and Memory ============


def _get_conversation_title_context(
    conversation_title: str | None,
    is_sports: bool,
    is_language: bool,
    is_planning: bool,
) -> str | None:
    """Title-awareness block for normal conversations.

    Program conversations (sports/language/planner) keep their titles, so the
    agent is not told about retitling there.
    """
    if not conversation_title or is_sports or is_language or is_planning:
        return None
    return CONVERSATION_TITLE_CONTEXT_PROMPT.format(title=conversation_title)


# ============ Helper Functions ============


def get_force_tools_prompt(force_tools: list[str]) -> str:
    """Build a prompt instructing the LLM to use specific tools.

    Args:
        force_tools: List of tool names to force (e.g., ["web_search"])

    Returns:
        A formatted instruction string
    """
    tool_list = "\n".join(f"- {tool}" for tool in force_tools)
    return f"""
# IMPORTANT: Mandatory Tool Usage
Before responding to this query, you MUST use the following tools:
{tool_list}

Call each required tool first, then provide your response based on the results. Do not skip this step."""


def _get_preferred_language(user_id: str | None) -> str | None:
    """The user's primary-language setting, or None for auto."""
    if not user_id:
        return None
    try:
        user = db.get_user_by_id(user_id)
        return user.preferred_language if user else None
    except Exception:  # noqa: BLE001 - personalization must never break prompts
        logger.debug("Preferred language lookup failed", exc_info=True)
        return None


def get_user_context(user_name: str | None = None, user_id: str | None = None) -> str:
    """Build user context for the system prompt based on configuration.

    Includes location and other contextual information that helps the assistant
    provide more relevant, personalized responses.

    Args:
        user_name: The user's name from JWT authentication
        user_id: The user's id, used to look up the primary-language setting

    Returns:
        User context string, or empty string if no context is configured.
    """
    context_parts: list[str] = []

    # User name context
    if user_name:
        context_parts.append(f"""## User
The user's name is {user_name}. Use it naturally when appropriate (greetings, personalized responses), but don't overuse it.""")

    # Primary language: fixes English replies to system-generated triggers
    preferred_language = _get_preferred_language(user_id)
    if preferred_language:
        context_parts.append(f"""## Language
The user's primary language is {preferred_language}. Always respond in {preferred_language} — including to system-generated messages (see "System-Generated Messages"). Deviate only when the user explicitly writes in a different language, asks for another language, or a more specific instruction applies (such as the language tutor's target-language immersion gradient).""")

    # Location context: device fix > saved places > static env fallback
    location_lines: list[str] = []
    device_loc = get_location_context()
    if device_loc:
        locality = _reverse_geocode_locality(device_loc["lon"], device_loc["lat"])
        if locality:
            location_lines.append(
                f"The user is currently near {locality} (live device location). "
                "Use it for 'near me' requests, local recommendations, and as the "
                "default origin for routes."
            )
    saved_lines = _get_saved_places_lines(user_id)
    if saved_lines:
        location_lines.append(
            "Saved places (usable by name in search_places/get_route):\n" + "\n".join(saved_lines)
        )
    if not location_lines and Config.USER_LOCATION:
        location_lines.append(f"The user is located in {Config.USER_LOCATION}.")
    if location_lines:
        location_lines.append(
            "Use the location for measurement units, local currency, locally "
            "available services, local regulations/holidays/customs, and "
            "date/time formats."
        )
        context_parts.append("## Location\n" + "\n\n".join(location_lines))

    if not context_parts:
        return ""

    return "\n\n# User Context\n" + "\n\n".join(context_parts)


def get_static_prompt_for_profile(profile: str) -> str:
    """Return only the static (cacheable) portion of the system prompt for a given profile.

    This is used by the context cache to create a cached prompt that doesn't change
    across requests. Dynamic content (date, user context, memories, program KV data)
    is added separately.

    Args:
        profile: One of "standard", "anonymous", "planning", "sports", "language"

    Returns:
        Static prompt string suitable for caching
    """
    prompt = BASE_SYSTEM_PROMPT
    # All profiles get base tools
    prompt += TOOLS_SYSTEM_PROMPT_BASE
    prompt += skills_index_prompt()
    # Places docs are env-stable (key presence), so the cached prefix stays stable
    if is_mapy_configured():
        prompt += TOOLS_SYSTEM_PROMPT_PLACES
    # All non-anonymous profiles get productivity tools (mirrors get_system_prompt)
    if profile in ("standard", "planning", "sports", "language"):
        prompt += TOOLS_SYSTEM_PROMPT_PRODUCTIVITY
    # All profiles get context/citation section
    prompt += TOOLS_SYSTEM_PROMPT_CONTEXT
    # Memory instructions are static; only the memory *list* is per-request.
    # Anonymous profiles have no memory tool bound, so they get neither.
    if profile != "anonymous":
        prompt += "\n\n" + get_memory_instructions_prompt()
    # Planning profile gets the planner prompt
    if profile == "planning":
        prompt += PLANNER_SYSTEM_PROMPT
    # Program profiles get the full (program-agnostic) instructions; the
    # program identity and KV data arrive via the dynamic context
    if profile == "sports":
        prompt += PROGRAM_STATIC_PREAMBLE + SPORTS_TRAINER_SYSTEM_PROMPT.format(
            program_name="<program_name>",
            program_id="<program_id>",
            kv_data_section=PROGRAM_STATIC_KV_NOTE,
        )
    if profile == "language":
        prompt += PROGRAM_STATIC_PREAMBLE + LANGUAGE_TUTOR_SYSTEM_PROMPT.format(
            program_name="<program_name>",
            program_id="<program_id>",
            kv_data_section=PROGRAM_STATIC_KV_NOTE,
        )
    return prompt


def get_dynamic_prompt_parts(
    force_tools: list[str] | None = None,
    user_name: str | None = None,
    user_id: str | None = None,
    custom_instructions: str | None = None,
    anonymous_mode: bool = False,
    is_planning: bool = False,
    dashboard_data: dict[str, Any] | None = None,
    planner_dashboard_context: Any | None = None,
    is_sports: bool = False,
    sports_context: dict[str, Any] | None = None,
    is_language: bool = False,
    language_context: dict[str, Any] | None = None,
    conversation_title: str | None = None,
) -> str:
    """Return only the dynamic (per-request) parts of the prompt.

    Used in cached mode where the static prompt is in the cache
    and dynamic content is passed as a HumanMessage with [CONTEXT] markers.

    Args:
        force_tools: Optional list of tool names that must be used
        user_name: The user's name from JWT authentication
        user_id: The user's ID for memory retrieval
        custom_instructions: User-provided custom instructions
        anonymous_mode: If True, skip memory retrieval
        is_planning: If True, include dashboard context
        dashboard_data: Dashboard data dict for planner
        planner_dashboard_context: Refreshed dashboard data
        is_sports: If True, include sports context
        sports_context: Sports context dict with program info
        is_language: If True, include language context
        language_context: Language context dict with program info

    Returns:
        Dynamic prompt string
    """
    from datetime import datetime

    now = datetime.now().astimezone()
    parts: list[str] = [f"Current date and time: {now.strftime('%A %Y-%m-%d %H:%M %Z')}"]

    user_context = get_user_context(user_name, user_id)
    if user_context:
        parts.append(user_context)

    if custom_instructions and custom_instructions.strip():
        parts.append(CUSTOM_INSTRUCTIONS_PROMPT.format(instructions=custom_instructions.strip()))

    title_context = _get_conversation_title_context(
        conversation_title, is_sports, is_language, is_planning
    )
    if title_context:
        parts.append(title_context)

    if user_id and not anonymous_mode:
        # Instructions live in the cached static prefix; only the list is dynamic
        parts.append(get_user_memories_list_prompt(user_id))

    if is_planning:
        active_dashboard = (
            planner_dashboard_context if planner_dashboard_context else dashboard_data
        )
        if active_dashboard:
            parts.append(get_dashboard_context_prompt(active_dashboard))

    if is_sports and sports_context:
        parts.append(format_program_dynamic_context("sports", sports_context))

    if is_language and language_context:
        parts.append(format_program_dynamic_context("language", language_context))

    if force_tools:
        parts.append(get_force_tools_prompt(force_tools))

    return "\n\n".join(parts)


def get_system_prompt(
    with_tools: bool = True,
    force_tools: list[str] | None = None,
    user_name: str | None = None,
    user_id: str | None = None,
    custom_instructions: str | None = None,
    anonymous_mode: bool = False,
    is_planning: bool = False,
    dashboard_data: dict[str, Any] | None = None,
    planner_dashboard_context: Any | None = None,
    is_autonomous: bool = False,
    agent_context: dict[str, Any] | None = None,
    is_sports: bool = False,
    sports_context: dict[str, Any] | None = None,
    is_language: bool = False,
    language_context: dict[str, Any] | None = None,
    conversation_title: str | None = None,
) -> str:
    """Build the system prompt, optionally including tool instructions.

    Args:
        with_tools: Whether tools are available
        force_tools: List of tool names that must be used (e.g., ["web_search", "image_generation"])
        user_name: The user's name from JWT authentication
        user_id: The user's ID for memory retrieval
        custom_instructions: User-provided custom instructions for LLM behavior
        anonymous_mode: If True, skip memory retrieval and injection
        is_planning: If True, include planner-specific system prompt with dashboard context
        dashboard_data: Dashboard data dict to inject into planner prompt (required if is_planning=True)
        planner_dashboard_context: Contextvar value for refreshed dashboard data (optional)
        is_autonomous: If True, include autonomous agent-specific system prompt
        agent_context: Agent context dict with keys: name, description, schedule, timezone, goals, tools, trigger_type
        is_sports: If True, include sports trainer system prompt
        sports_context: Sports context dict with keys: program_name, program_id
        is_language: If True, include language tutor system prompt
        language_context: Language context dict with keys: program_name, program_id
    """
    from src.agent.tools import get_available_tools

    # Include timezone info using astimezone() to get local timezone
    now = datetime.now().astimezone()
    date_context = f"\n\nCurrent date and time: {now.strftime('%A %Y-%m-%d %H:%M %Z')}"

    prompt = BASE_SYSTEM_PROMPT

    # Add user context if configured
    prompt += get_user_context(user_name, user_id)

    title_context = _get_conversation_title_context(
        conversation_title, is_sports, is_language, is_planning
    )
    if title_context:
        prompt += title_context

    if with_tools and get_available_tools():
        # Always include base tools documentation
        prompt += TOOLS_SYSTEM_PROMPT_BASE
        prompt += skills_index_prompt()
        # Include places/routing docs only when the Mapy.com key is configured
        if is_mapy_configured():
            prompt += TOOLS_SYSTEM_PROMPT_PLACES
        # Include productivity tools (Todoist, Calendar) docs only when NOT in anonymous mode
        if not anonymous_mode:
            prompt += TOOLS_SYSTEM_PROMPT_PRODUCTIVITY
        # Always include context and citation section
        prompt += TOOLS_SYSTEM_PROMPT_CONTEXT

    # Add planner-specific prompt if in planning mode
    if is_planning:
        prompt += PLANNER_SYSTEM_PROMPT
        # Check for updated dashboard context from refresh_planner_dashboard tool
        # If the tool was called mid-conversation, use the refreshed data
        active_dashboard = (
            planner_dashboard_context if planner_dashboard_context else dashboard_data
        )
        # Add dashboard context if available
        if active_dashboard:
            prompt += get_dashboard_context_prompt(active_dashboard)

    # Add sports trainer prompt if in sports mode
    if is_sports and sports_context:
        prompt += SPORTS_TRAINER_SYSTEM_PROMPT.format(
            program_name=sports_context.get("program_name", "Training"),
            program_id=sports_context.get("program_id", "program"),
            kv_data_section=format_sports_kv_data(sports_context),
        )

    # Add language tutor prompt if in language mode
    if is_language and language_context:
        prompt += LANGUAGE_TUTOR_SYSTEM_PROMPT.format(
            program_name=language_context.get("program_name", "Language"),
            program_id=language_context.get("program_id", "program"),
            kv_data_section=format_language_kv_data(language_context),
        )

    # Add autonomous agent prompt if running as an agent
    if is_autonomous and agent_context:
        prompt += "\n\n" + get_autonomous_agent_prompt(
            agent_name=agent_context.get("name", "Agent"),
            agent_description=agent_context.get("description"),
            agent_schedule=agent_context.get("schedule"),
            agent_timezone=agent_context.get("timezone", "UTC"),
            agent_goals=agent_context.get("goals"),
            agent_tools=agent_context.get("tools", []),
            trigger_type=agent_context.get("trigger_type", "manual"),
            fresh_context=bool(agent_context.get("fresh_context", False)),
        )

    # Add custom instructions if provided
    if custom_instructions and custom_instructions.strip():
        prompt += "\n\n" + CUSTOM_INSTRUCTIONS_PROMPT.format(
            instructions=custom_instructions.strip()
        )

    # Add user memories if user_id is provided (skip in anonymous mode)
    if user_id and not anonymous_mode:
        prompt += "\n\n" + get_user_memories_prompt(user_id)

    # Add force tools instruction if specified
    if force_tools:
        prompt += get_force_tools_prompt(force_tools)

    return prompt + date_context
