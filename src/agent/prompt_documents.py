"""The per-user saved-documents list for the chat context (document memory).

One line per live, unexpired document: what it is, what is in it and when to
use it. Empty when the user has none, so chats without documents pay nothing.
"""

from src.agent.prompt_texts.documents import DOCUMENTS_SYSTEM_PROMPT
from src.config import Config
from src.db.models import db
from src.db.models.dataclasses import Document
from src.utils.clock import local_today, to_local
from src.utils.memory_ids import short_memory_id


def get_documents_instructions_prompt() -> str:
    """The static guidance (cached prefix; only where the tools are bound)."""
    return DOCUMENTS_SYSTEM_PROMPT.strip()


def _document_line(doc: Document) -> str:
    dates = f"{doc.filename}, saved {to_local(doc.created_at).strftime('%Y-%m-%d')}"
    if doc.valid_until:
        dates += f", until {doc.valid_until.isoformat()}"
    fields = [
        f"- {short_memory_id(doc.id)}",
        " ".join(doc.title.split()),
        dates,
        " ".join(doc.summary.split()),
        "Use for: " + " ".join(doc.use_for.split()),
    ]
    return " | ".join(fields)


def get_user_documents_list_prompt(user_id: str) -> str:
    """The user's saved documents, or "" when there are none."""
    today = local_today()
    docs = [doc for doc in db.list_documents(user_id) if not doc.expired(today)]
    if not docs:
        return ""
    header = f"## Saved documents ({len(docs)}/{Config.DOCUMENTS_MAX_ENTRIES})"
    return "\n".join([header, *(_document_line(doc) for doc in docs)])
