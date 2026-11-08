"""The standing-chat section of an ordinary chat prompt (src/agent/prompts.py).

Agents and sports / language programs are standing chats: writing in one is an
ordinary chat turn, plus this section with the chat's standing instructions and
data.
"""

STANDING_CHAT_SECTION = """# This Chat: {name}

This is a standing chat. Follow its standing instructions below for anything
in their scope; all your usual abilities and tools stay available.

{instructions}"""

STANDING_CHAT_DATA = """

## Data

{data}"""
