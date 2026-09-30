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
