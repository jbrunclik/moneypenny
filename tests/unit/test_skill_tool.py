"""The load_skill tool and its wiring into binding, permissions and the prompt."""

from src.agent import skills
from src.agent.permissions import ALWAYS_SAFE_TOOLS
from src.agent.tools.skills import load_skill


def test_returns_the_body_with_a_header() -> None:
    result = load_skill.invoke({"name": "office-documents"})
    assert result.startswith("Skill: office-documents")
    assert skills.get_skill("office-documents").body in result  # type: ignore[union-attr]


def test_unknown_skill_lists_valid_names() -> None:
    result = load_skill.invoke({"name": "excel-magic"})
    assert "Unknown skill" in result
    for skill in skills.list_skills():
        assert skill.name in result


def test_load_skill_passes_the_permission_gate() -> None:
    assert "load_skill" in ALWAYS_SAFE_TOOLS


def test_bound_for_chat_and_for_agents() -> None:
    from unittest.mock import MagicMock

    from src.agent.tools import get_tools_for_agent, get_tools_for_request

    assert "load_skill" in {t.name for t in get_tools_for_request()}
    agent = MagicMock(tool_permissions=[])
    assert "load_skill" in {t.name for t in get_tools_for_agent(agent)}


def test_index_is_in_the_cached_static_prompt() -> None:
    from src.agent.prompts import get_static_prompt_for_profile, get_system_prompt

    prompt = get_static_prompt_for_profile("standard")
    assert skills.skills_index_prompt() in prompt
    assert prompt == get_static_prompt_for_profile("standard")
    assert skills.skills_index_prompt() in get_system_prompt()


def test_recipes_moved_out_of_the_prompt() -> None:
    from src.agent.prompt_texts.core import TOOLS_SYSTEM_PROMPT_BASE
    from src.agent.prompt_texts.productivity import TOOLS_SYSTEM_PROMPT_PRODUCTIVITY

    moved = {
        "office-documents": "freeze_panes",
        "pdf-documents": "DejaVuSans-Bold.ttf",
        "browser-tactics": "consent-accept",
        "weekly-planning": "## Weekly Strategic Planning",
    }
    always_on = TOOLS_SYSTEM_PROMPT_BASE + TOOLS_SYSTEM_PROMPT_PRODUCTIVITY
    for name, marker in moved.items():
        assert marker not in always_on, f"{name} recipe still always-on"
        assert marker in skills.get_skill(name).body  # type: ignore[union-attr]
    assert "load_skill('office-documents')" in TOOLS_SYSTEM_PROMPT_BASE
    assert "load_skill('pdf-documents')" in TOOLS_SYSTEM_PROMPT_BASE


def test_loaded_skill_is_never_aged_mid_turn() -> None:
    """Aging truncates consumed results over AGENT_AGED_TOOL_RESULT_MAX_CHARS;
    a skill read in round 1 must still be whole in round 3."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from src.agent.graph import _age_consumed_tool_messages
    from src.config import Config

    body = "x" * (Config.AGENT_AGED_TOOL_RESULT_MAX_CHARS * 2)
    messages = [
        HumanMessage(content="log in and check"),
        AIMessage(content="", tool_calls=[{"name": "load_skill", "args": {}, "id": "c1"}]),
        ToolMessage(content=body, tool_call_id="c1", name="load_skill"),
        AIMessage(content="", tool_calls=[{"name": "browser", "args": {}, "id": "c2"}]),
        ToolMessage(content="{}", tool_call_id="c2", name="browser"),
    ]
    _age_consumed_tool_messages(messages)
    assert messages[2].content == body


def test_parallel_browser_guardrail_stays_always_on() -> None:
    from src.agent.prompt_texts.core import TOOLS_SYSTEM_PROMPT_BASE

    assert "Never issue several separate browser calls in parallel" in TOOLS_SYSTEM_PROMPT_BASE


def test_weekly_planning_does_not_claim_the_morning_briefing() -> None:
    """The scheduled Daily Briefing agent ("You produce a short morning
    briefing") must not be steered into the weekly planning session."""
    description = skills.get_skill("weekly-planning").description  # type: ignore[union-attr]
    assert "briefing" not in description.lower()
