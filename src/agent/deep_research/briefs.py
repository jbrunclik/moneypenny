"""Self-contained briefs for deep-research subagents (fresh contexts)."""

from src.agent.deep_research.plan import DeepResearchPlan

_RECENT_TURNS_MAX_CHARS = 2000
_PREVIOUS_REPORT_MAX_CHARS = 6000


def build_brief(plan: DeepResearchPlan, index: int, today: str, recent_turns: str) -> str:
    """Everything one subagent needs: it starts with no conversation history."""
    parts = [
        f"Today is {today}.",
        f"The user's question: {plan.question}",
    ]
    if plan.context:
        parts.append(f"About the user: {plan.context}")
    if recent_turns.strip():
        parts.append(
            f"Recent conversation (for context):\n{recent_turns[-_RECENT_TURNS_MAX_CHARS:]}"
        )
    if plan.previous_report:
        report = plan.previous_report[:_PREVIOUS_REPORT_MAX_CHARS]
        parts.append(
            f"An earlier research round already reported (build on it, do not repeat it):\n{report}"
        )
    others = [q for i, q in enumerate(plan.sub_questions) if i != index]
    if others:
        parts.append("Other agents are researching: " + "; ".join(others))
    parts.append(
        f"YOUR SUB-QUESTION: {plan.sub_questions[index]}\n\n"
        "Share important facts and leads with share_finding as you go."
    )
    return "\n\n".join(parts)
