"""Prompt for the post-answer grounding check (src/agent/grounding_check.py)."""

# Precision first: a false flag puts a wrong "not confirmed" note under a
# correct answer, which is worse than missing a real one. Formatted with
# str.format - keep literal braces doubled.
GROUNDING_CHECK_PROMPT = """You check an assistant's ANSWER against the web SOURCES it read this turn.

List the concrete, checkable specifics in the ANSWER that the SOURCES do not contain, or that the SOURCES contradict:
- names of shops, dealers, places, venues, restaurants, products or people
- prices, opening hours, dates, schedules and other figures

Do NOT list:
- general knowledge, advice, explanations, or the answer's own reasoning
- anything the ANSWER already marks as unverified, approximate or an estimate
- a specific the SOURCES state in other words, other formatting or another language

When unsure, do not list it. Copy each item exactly as it is written in the ANSWER.
Return an empty list when everything is supported.

SOURCES:
{sources}

ANSWER:
{answer}
"""
