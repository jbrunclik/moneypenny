"""Prompt for the post-answer grounding check (src/agent/grounding_check.py)."""

# Every claim gets a verdict; the server keeps a source number only when the
# copied passage is really in that page. Formatted with str.format - keep
# literal braces doubled.
GROUNDING_CHECK_PROMPT = """You check an assistant's ANSWER against the numbered web SOURCES it read this turn.

List the specific claims in the ANSWER about businesses, products, services, events, prices, opening hours, dates, times of events and contact details. Each claim is the SHORTEST phrase that states it, copied exactly from the ANSWER: a business name, or "Cena: kolem 1 200–1 600 Kč" - never a whole paragraph. If that phrase appears more than once in the ANSWER, extend it until it appears only once ("PřepiServis: … 800 Kč", not "800 Kč"). Go through the answer line by line, tables included: EVERY price or price range is its own claim.

Put every claim that is not supported (partial, contradicted, not_found) in "unsupported" - all of them. Put supported claims in "supported", but only those naming a business, product, price, opening hours, date or contact - never a town or region.

For each claim give a verdict:
- supported: a numbered SOURCE states it (in any wording or language). Give its number as source and copy the supporting passage exactly from that source as source_quote.
- partial: a SOURCE states part of it. Give source and source_quote for the part, and a reason naming the part that is missing.
- contradicted: a SOURCE says something different. Give source, the conflicting passage as source_quote, and a reason.
- not_found: no SOURCE supports it. Give a reason.

If only the UNNUMBERED text supports a claim, it is supported with no source.

A reason is one short sentence in the ANSWER's language, about the sources ("Stránky popisují jen SPZ Služby; PřepiServis v nich není.").

A sentence in which the ANSWER says it verified, checked or confirmed something is a claim too: contradicted or not_found when the SOURCES don't back it.

NEVER list:
- the answer's own plan, schedule, suggested times, durations or itinerary ("10:30 departure", "about 30 minutes") - these are proposals, not claims
- well-known places and geography: towns, villages, hills, rivers, regions, roads, countries
- general knowledge, advice, explanations, or the answer's own reasoning
- anything the ANSWER already marks as unverified, approximate or an estimate
- anything in KNOWN

KNOWN (always supported - never list these):
{known}

SOURCES:
{sources}

ANSWER:
{answer}
"""
