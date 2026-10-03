"""propose_deep_research: the agent offers a deep research run.

Side-effect free: the offer is read off the tool call when the reply is saved
(src/agent/deep_research/offer.py extract_offer). The result steers the model
to finish with a brief answer.
"""

from langchain_core.tools import tool

from src.agent.prompt_texts.deep_research import OFFER_TOOL_DESCRIPTION


@tool(description=OFFER_TOOL_DESCRIPTION)
def propose_deep_research(
    question: str, context: str, sub_questions: list[str], run_now: bool = False
) -> str:
    if run_now:
        return "Deep research will start right after this turn. Say so in one short sentence."
    return (
        "Offer recorded. Now give your brief answer; the user decides whether to "
        "run the deep research."
    )
