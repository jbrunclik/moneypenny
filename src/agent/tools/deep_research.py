"""propose_deep_research: the agent offers a deep research run.

Side-effect free: the offer is read off the tool call when the reply is saved
(src/agent/deep_research/offer.py extract_offer) and becomes the reply's
card. The result steers the model to finish with a brief answer.
"""

from langchain_core.tools import tool

from src.agent.deep_research.offer import KIND, PlanError, validate_plan
from src.agent.deep_research.plan import apply_research, decline_research
from src.agent.prompt_texts.deep_research import OFFER_TOOL_DESCRIPTION
from src.agent.proposals import register_kind


@tool(description=OFFER_TOOL_DESCRIPTION)
def propose_deep_research(
    question: str, context: str, sub_questions: list[str], run_now: bool = False
) -> str:
    try:
        validate_plan(sub_questions, context)
    except PlanError as e:
        # No card would appear: tell the model so it can fix the plan
        return f"Offer NOT recorded: {e} Fix the plan and call propose_deep_research again."
    if run_now:
        return (
            "Offer recorded. Give your brief answer and say the user will see the plan "
            "before it starts."
        )
    return (
        "Offer recorded. Now give your brief answer; the user decides whether to "
        "run the deep research."
    )


# Starting is the turn itself: only a streamed turn can act on a typed yes
register_kind(KIND, apply_research, decline=decline_research, stream_only=True)
