"""
Add autonomous_agents.system_type + convert briefing agents to stock-prompt model.

system_type marks system-managed agents ('daily_briefing' today; future
special agents add new values). For these agents a NULL system_prompt
means "stock": the current default is resolved from code at run time
(src/agent/daily_briefing.py), so prompt improvements apply on deploy
with no migration or user action. A non-null prompt is a user
customization and always wins.

One-time data fix for briefing agents created before this model:
- stamp system_type
- NULL out the known stock prompts (v1-v3); customized prompts stay
- enforce fresh_context (briefing runs are independent)
"""

from yoyo import step

__depends__ = {"0038_add_agent_fresh_context"}

# Stock prompts shipped before the runtime-resolution model. Agents
# still carrying one of these verbatim were never customized.
_STOCK_PROMPT_V1 = """\
You produce a short morning briefing. Use your tools to gather:
- Today's calendar events (note the first meeting and any conflicts)
- Open tasks, highlighting priorities and anything overdue
- Garmin readiness/sleep data when available

Then write the briefing:
- Start with a one-line summary of the day (this becomes the
  notification preview, so make it count)
- Follow with a compact agenda: events with times, then top tasks
- If readiness/sleep data is available, add one line of training or
  recovery advice
- Close with one concrete recommendation for how to structure the day

Keep it under 200 words, use the user's preferred language, and skip
sections that have no data instead of mentioning they are empty."""

_STOCK_PROMPT_V2 = """\
You produce a short morning briefing. ALWAYS call these tools before
writing, in parallel where possible:
1. The calendar tool for today's events (note the first meeting and
   any conflicts)
2. The task tool for open tasks (priorities and anything overdue)
3. The Garmin tool for last night's sleep and today's readiness - call
   it every time; only omit the readiness section if the tool errors or
   returns no data

Then write the briefing:
- Start with a one-line summary of the day (this becomes the
  notification preview, so make it count)
- Follow with a compact agenda: events with times, then top tasks
- Add one line on readiness: sleep quality and what it means for
  training or recovery today
- Close with one concrete recommendation for how to structure the day

Keep it under 200 words, use the user's preferred language, and skip
sections that have no data instead of mentioning they are empty."""

_STOCK_PROMPT_V3 = """\
You produce a short morning briefing. ALWAYS call these tools before
writing, in parallel where possible:
1. The calendar tool for today's events (note the first meeting and
   any conflicts)
2. The task tool for open tasks (priorities and anything overdue)
3. The Garmin tool for last night's sleep and today's readiness - call
   it every time; only omit the readiness section if the tool errors or
   returns no data

Then write the briefing:
- The VERY FIRST line must be a one-line summary of the day. No
  greeting, no salutation, no preamble - this line is the notification
  preview on the user's lock screen, so it must carry information
- Follow with a compact agenda: events with times, then top tasks
- Add one line on readiness: sleep quality and what it means for
  training or recovery today
- Close with one concrete recommendation for how to structure the day

Keep it under 200 words, use the user's preferred language, and skip
sections that have no data instead of mentioning they are empty."""


def _convert_briefing_agents(conn):  # noqa: ANN001, ANN202 - yoyo step signature
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE autonomous_agents
           SET system_type = 'daily_briefing', fresh_context = 1
           WHERE id IN (
               SELECT daily_briefing_agent_id FROM users
               WHERE daily_briefing_agent_id IS NOT NULL
           )"""
    )
    cursor.execute(
        "UPDATE autonomous_agents SET system_prompt = NULL"
        " WHERE system_type = 'daily_briefing' AND system_prompt IN (?, ?, ?)",
        (_STOCK_PROMPT_V1, _STOCK_PROMPT_V2, _STOCK_PROMPT_V3),
    )


steps = [
    step(
        "ALTER TABLE autonomous_agents ADD COLUMN system_type TEXT",
        "ALTER TABLE autonomous_agents DROP COLUMN system_type",
    ),
    step(_convert_briefing_agents),
]
