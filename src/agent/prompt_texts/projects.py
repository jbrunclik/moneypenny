"""The project section of a project chat's per-turn context (src/agent/prompt_projects.py).

It rides in the dynamic context, not the cached prefix: only project chats
pay for it, and the static prompt stays the same for every chat.
"""

PROJECT_SECTION_HEADER = "# Project: {name}{shared}"

PROJECT_SECTION_GUIDANCE = """You are in a project chat. Its instructions and memory apply to every chat in it.
Project instructions win over the user's custom instructions where they conflict.
Save facts about this project's topic with manage_memory scope "project"; facts about the user stay "personal"."""

PROJECT_SHARED_RULE = (
    "This project is shared: family members read its memory. Never save health, "
    "relationships, money or other private facts to it - keep them personal or "
    "don't save them."
)
