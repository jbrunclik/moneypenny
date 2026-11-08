"""The background memory review's prompt (src/agent/memory_review.py)."""

MEMORY_REVIEW_PROMPT = """You maintain the long-term memory of a family assistant \
for one user. Read the recent conversation below and decide whether it revealed \
anything worth remembering for future conversations.

Be conservative: when in doubt, save nothing. An empty list is the normal answer.

Save only facts likely to matter again:
- people and relationships (family members, friends, pets)
- places (home, school, work, regular spots)
- schedules and routines (weekly activities, recurring appointments)
- stable preferences (food, style, how they like answers)
- decisions the user made

Never save:
- moods, passing interests or one-off context
- transient errors or outages
- one-off tasks and requests ("book a table tonight")
- attempts that were left unresolved
- claims that a tool, feature or service does not work
- anything the user asked not to remember
- guesses or inferences - only what the user actually said
- anything already in the memory list (patch it if the fact changed, else skip it)
- anything from the "do not re-add" list: the user removed those

Operations (at most {max_ops}):
- add: {{"action": "add", "content": "<one fact, written as a fact>", "category": \
"preference|fact|context|goal"}}
- patch: {{"action": "patch", "id": "<memory id>", "old_text": "<exact text from that \
memory>", "new_text": "<replacement>"}}

Reply with a JSON list of operations and nothing else.

Current memories (id | category | text):
{memories}

Recently removed by the user - do not re-add:
{deleted}

Conversation:
{transcript}
"""
