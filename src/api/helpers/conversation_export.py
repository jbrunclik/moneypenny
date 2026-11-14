"""A conversation as a Markdown file: title, who said what and when, attachments.

Content goes out as written - it is already Markdown, so code blocks, tables
and links survive. Attachments, sources and artifacts are listed by name (the
file itself stays in the app). An empty reply placeholder (a turn still
running, or one whose worker died) is left out.
"""

import re
import unicodedata
from datetime import datetime
from urllib.parse import quote

from src.api.utils import is_empty_placeholder
from src.config import Config
from src.db.models.dataclasses import Message
from src.enums import MessageRole
from src.utils.clock import to_local

_TIME_FORMAT = "%Y-%m-%d %H:%M"
_SLUG_MAX_CHARS = 60


def _message_block(message: Message) -> str:
    who = "You" if message.role == MessageRole.USER else Config.APP_NAME
    parts = [
        f"**{who}** · {to_local(message.created_at).strftime(_TIME_FORMAT)}",
        message.content.strip(),
    ]
    names = [f.get("name") for f in message.files or [] if f.get("name")]
    if names:
        parts.append("Attachments: " + ", ".join(str(n) for n in names))
    parts.extend(f"Artifact: {artifact['title']}" for artifact in message.artifacts or [])
    sources = [s for s in message.sources or [] if s.get("url")]
    if sources:
        parts.append(
            "Sources:\n"
            + "\n".join(f"- [{s.get('title') or s['url']}]({s['url']})" for s in sources)
        )
    return "\n\n".join(p for p in parts if p)


def conversation_markdown(title: str, messages: list[Message], exported_at: datetime) -> str:
    """The whole conversation as one Markdown document."""
    when = to_local(exported_at).strftime(_TIME_FORMAT)
    blocks = [_message_block(m) for m in messages if not is_empty_placeholder(m)]
    header = f"# {title}\n\n*Exported from {Config.APP_NAME} on {when}*"
    return "\n\n---\n\n".join([header, *blocks]) + "\n"


def _slug(title: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_title).strip("-").lower()
    return slug[:_SLUG_MAX_CHARS].rstrip("-") or "conversation"


def content_disposition(title: str, exported_at: datetime) -> str:
    """An attachment header naming the file after the title (UTF-8 for Czech
    titles, an ASCII fallback for clients that only read `filename`)."""
    date = to_local(exported_at).strftime("%Y-%m-%d")
    ascii_name = f"{_slug(title)}-{date}.md"
    readable = re.sub(r'[\\/:*?"<>|]+', " ", title).strip() or "conversation"
    utf8_name = quote(f"{readable} {date}.md", safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"
