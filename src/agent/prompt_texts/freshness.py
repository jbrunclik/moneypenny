"""Prompt for the freshness gate (src/agent/freshness.py).

Formatted with str.format - keep literal braces doubled.
"""

FRESHNESS_GATE_PROMPT = """You decide whether an assistant must look things up on the web BEFORE answering the user's latest message, because the right answer depends on facts that are new or may have changed. The assistant's training data ends well before TODAY, so anything from roughly the last two years, or happening now, is unknown to it or may be stale.

TODAY: {today}

Answer lookup=true when answering needs any of:
- events, announcements, launches, releases, keynotes, elections, results, scores or decisions from the last two years, or upcoming ones - also a follow-up asking for more about such an event already discussed
- who holds an office or role now, what a company, party or product is doing now
- an opinion, advice or strategy about a CURRENT situation - politics, parties and who leads them, a company, a market, a team, a war - because the answer will state where things stand now (who leads, who left, who allied); "what do you think", "co by se mělo stát" or "who should lead it" about such a situation is NOT timeless
- current products, specs, prices, availability, rules, laws, schedules or opening hours
- the user disputes, corrects or questions a fact, or asks to check, find, verify or look something up ("ne, bylo tam…", "najdi si to", "ověř to")

Answer lookup=false for: greetings, thanks, short acknowledgements, opinions and advice on timeless or personal matters that need no new facts, writing, editing, translating or summarising given text, maths, code, timeless knowledge, history older than two years, the user's own data (calendar, tasks, memories, files, fitness), and anything about the conversation itself.

Set disputed=true when the user's latest message disputes, corrects or doubts a fact the assistant stated ("to není pravda", "ne, bylo tam…", "jsi si jistý?").

Set think_hard=true when a good answer needs careful reasoning or a plan of several steps: recommending, comparing or choosing products, places or services; planning a trip, an event, a schedule or a training block; research that needs several sources or a thorough report; a task with several parts or constraints to satisfy; maths, data, code or a file to analyse; a decision or advice with real trade-offs; and whenever the user disputes a fact. Set think_hard=false for everything else - most turns: chit-chat, thanks, a quick fact or definition, a short follow-up, translating, rewriting, shortening or summarising given text, a single simple action on the user's data (add a task, check the calendar), and casual advice.

When lookup=true, write 1-3 web search queries that will find CURRENT pages: in the language the facts are best covered in, and EVERY query anchored in time - the event's name with its month and year, or the current year (e.g. "Apple September 2026 event Siri AI external models", "náměstek pro dopravu Praha 2026"). A query without a year finds old pages, so it is never allowed. For an opinion or strategy question, query the current state of the people and groups it names: who leads each now, who left or split off ("generální ředitel Intelu 2026", "trenér Sparty Praha říjen 2026").

PREVIOUS ASSISTANT REPLY (may be empty):
{previous}

USER'S LATEST MESSAGE:
{user}
"""
