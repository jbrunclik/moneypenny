"""Prompts for deep research (src/agent/deep_research/, tools/deep_research.py)."""

OFFER_TOOL_DESCRIPTION = """Offer the user a deep research run on this question (several minutes of parallel web research by subagents, then a report with numbered sources). The user sees your plan and a cost estimate, can edit the plan, and decides.

Offer it ONLY when the question needs several options compared (products, providers, agencies, trips, financial products), several current facts checked across sources, or a decision with trade-offs - and your quick answer cannot do that well. NEVER for single facts, definitions, chit-chat, or a question your answer already covers well.

Call it together with a brief normal answer. Set run_now only when the user explicitly asked for deep or thorough research.

question: the user's question in their own words.
context: what matters about the user for this question (from the conversation and memories), one short paragraph.
sub_questions: 3-6 concrete, separately researchable questions, in the user's language."""
