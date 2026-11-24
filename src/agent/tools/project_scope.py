"""The project a chat turn's tools work in (projects design, Nov 2026).

Read from the conversation row each time, not a contextvar: tools run on the
graph's threads, and contextvars do not cross them.
"""

from src.db.models import db


def chat_project_id(conversation_id: str | None, user_id: str) -> str | None:
    """The project the chat is filed under, if the user is still a member."""
    if not conversation_id:
        return None
    project = db.project_for_conversation(conversation_id, user_id)
    return project.id if project else None
