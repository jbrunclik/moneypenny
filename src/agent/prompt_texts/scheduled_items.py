"""Run prompts for watchers and recurring items set from chat (src/agent/item_runner.py).

Sent as the run's message; the reply is posted into the chat that set the
item, so it is written to the user. Markers: [SILENT] (nothing new - nothing
is posted) and, for watchers, [DONE] (the stop condition is met).
"""

WATCHER_RUN_PROMPT = """You are checking something on the user's behalf, on a schedule. Your reply is posted into their chat with you as a new message.

What to check: {text}
Stop when: {end_condition}
Your previous report: {last_result}

Check it now with your tools (public web pages only). Then reply in the language the task above is written in, with exactly one of:
- [SILENT] - and nothing else - when nothing changed since your previous report, or there is still nothing worth telling;
- [DONE] followed by a short report, when the stop condition is met (say what you found and where);
- a short report of what changed, when something changed but the stop condition is not met yet.
Never repeat your previous report."""

RECURRING_RUN_PROMPT = """You are doing a regular task for the user, on a schedule. Your reply is posted into their chat with you as a new message.

The task: {text}
Your previous report: {last_result}

Do it now with your tools. Then reply in the language the task above is written in: a short report - or exactly [SILENT], and nothing else, when there is nothing worth telling this time."""

NO_PREVIOUS_RESULT = "(none - this is the first run)"
