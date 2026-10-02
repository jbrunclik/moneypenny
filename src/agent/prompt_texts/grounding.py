"""Prompt for the post-answer grounding check (src/agent/grounding_check.py)."""

# Precision first: a false flag puts a wrong "unverified" marker on a correct
# fact, which is worse than missing a real one. Formatted with
# str.format - keep literal braces doubled.
GROUNDING_CHECK_PROMPT = """You check an assistant's ANSWER against the web SOURCES it read this turn.

List the claims about specific businesses, events and services in the ANSWER that neither the SOURCES nor the KNOWN facts support, or that the SOURCES contradict:
- a named shop, restaurant, cafe, venue, dealer, product or service, stated as real or as offering something
- its opening hours, prices, stock, contact details, or the date and time of an event

Go through the answer line by line, tables included, and list each one, not just examples.

NEVER list:
- the answer's own plan, schedule, suggested times, durations or itinerary ("10:30 departure", "11:30-13:30 lunch", "about 30 minutes") - these are proposals, not claims
- well-known places and geography: towns, villages, hills, rivers, regions, roads, countries
- general knowledge, advice, explanations, or the answer's own reasoning
- anything the ANSWER already marks as unverified, approximate or an estimate
- a specific the SOURCES state in other words, other formatting or another language

Also list, as false_claims, every sentence in which the ANSWER says it verified, checked or confirmed something that the SOURCES do not support. Copy the whole sentence exactly as written.

When unsure, do not list it. Copy each item exactly as it is written in the ANSWER; an item is a name, price, date or time, never a whole sentence.

KNOWN (always supported - never list these):
{known}

SOURCES:
{sources}

ANSWER:
{answer}
"""
