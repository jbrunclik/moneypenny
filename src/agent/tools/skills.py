"""load_skill: return a built-in skill's instructions on demand (see src/agent/skills)."""

from langchain_core.tools import tool

from src.agent.skills import get_skill, list_skills


@tool
def load_skill(name: str) -> str:
    """Load the detailed instructions of a skill listed under "# Skills" in your
    instructions. Call it BEFORE doing a task that matches the skill, then continue
    with the task in the same turn - loading a skill does not finish your turn.

    Args:
        name: The skill name exactly as listed (e.g. "office-documents").
    """
    skill = get_skill(name.strip())
    if skill is None:
        valid = ", ".join(s.name for s in list_skills())
        return f"Unknown skill '{name}'. Valid skills: {valid}."
    return f"Skill: {skill.name}\nFollow these instructions for the current task.\n\n{skill.body}"
