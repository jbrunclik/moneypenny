"""Prompt for the post-answer grounding check (src/agent/grounding_check.py)."""

# Precision first: a false flag puts a wrong "unverified" marker on a correct
# fact, which is worse than missing a real one. Formatted with
# str.format - keep literal braces doubled.
GROUNDING_CHECK_PROMPT = """You check an assistant's ANSWER against the web SOURCES it read this turn.

List EVERY concrete, checkable specific in the ANSWER that neither the SOURCES nor the KNOWN facts contain, or that the SOURCES contradict. Go through the answer line by line, including tables, lists and any "verified" claims the answer makes about itself; list each one, not just examples:
- names of shops, dealers, places, venues, restaurants, products or people
- prices, opening hours, dates, schedules and other figures

Do NOT list:
- general knowledge, advice, explanations, or the answer's own reasoning
- anything the ANSWER already marks as unverified, approximate or an estimate
- a specific the SOURCES state in other words, other formatting or another language

Also list, as false_claims, every sentence in which the ANSWER says it verified, checked or confirmed something that the SOURCES do not support. Copy the whole sentence exactly as written.

When unsure, do not list it. Copy each item exactly as it is written in the ANSWER; an item is a name, price, date or figure, never a whole sentence.
Return an empty list when everything is supported.

KNOWN (always supported - never list these):
{known}

SOURCES:
{sources}

ANSWER:
{answer}
"""
