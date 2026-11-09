"""What's new: announcements written as repo files and posted, once per
user, into each user's read-only What's new chat (docs/features/whats-new.md).

An announcement is ``announcements/YYYY-MM-DD-slug.md`` with a Czech and an
English version, each starting with its ``# Title``::

    <!-- lang: cs -->
    # Titulek
    Text...

    <!-- lang: en -->
    # Title
    Text...

App startup posts every announcement a user has not had yet, to the users
who existed on its date; the per-user claim makes it once however many
workers start at the same time. Each post sends a push.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from src.config import Config
from src.db.models import db
from src.enums import MessageRole
from src.services.push import send_push_to_user
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.db.models import User

logger = get_logger(__name__)

LANGUAGES = ("cs", "en")
CHAT_TITLES = {"cs": "Novinky", "en": "What's new"}
_LANG_MARKER = re.compile(r"^<!--\s*lang:\s*(\w+)\s*-->\s*$", re.MULTILINE)
_FILE_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-[a-z0-9-]+$")
_PUSH_BODY_MAX_CHARS = 140


class AnnouncementError(ValueError):
    """An announcement file that cannot be posted (and why)."""


@dataclass(frozen=True)
class Version:
    """An announcement in one language: its title and the whole message."""

    title: str
    body: str


@dataclass(frozen=True)
class Announcement:
    id: str
    day: date
    versions: dict[str, Version]


def parse_announcement(path: Path) -> Announcement:
    """An announcement file, both languages; AnnouncementError when invalid."""
    match = _FILE_NAME.match(path.stem)
    if not match:
        raise AnnouncementError(f"{path.name}: name it YYYY-MM-DD-slug.md")
    parts = _LANG_MARKER.split(path.read_text(encoding="utf-8"))
    # [preamble, lang, text, lang, text, ...]
    versions = {
        lang: _version(path, lang, text)
        for lang, text in zip(parts[1::2], parts[2::2], strict=True)
    }
    if missing := [lang for lang in LANGUAGES if lang not in versions]:
        raise AnnouncementError(f"{path.name}: missing the {', '.join(missing)} version")
    return Announcement(path.stem, date.fromisoformat(match.group(1)), versions)


def _version(path: Path, lang: str, text: str) -> Version:
    body = text.strip()
    first = body.splitlines()[0] if body else ""
    if not first.startswith("# ") or len(body.splitlines()) < 2:
        raise AnnouncementError(f"{path.name}: the {lang} version needs a '# Title' and text")
    title = first.removeprefix("# ").strip()
    # Posted as a level-2 heading: a chat bubble's H1 shouts
    return Version(title, "\n".join([f"## {title}", *body.splitlines()[1:]]))


def load_announcements(directory: Path) -> list[Announcement]:
    """Every valid announcement, oldest first; an invalid file is logged and skipped."""
    announcements = []
    for path in sorted(directory.glob("*.md")):
        try:
            announcements.append(parse_announcement(path))
        except ValueError as e:  # AnnouncementError is one; a bad date the other
            logger.exception("Announcement skipped", extra={"file": path.name, "error": str(e)})
    return announcements


def language_for(user: User) -> str:
    """The user's announcement language: English when they chose it, else Czech."""
    return "en" if (user.preferred_language or "").casefold() == "english" else "cs"


def post_pending_announcements(directory: Path | None = None) -> int:
    """Post every announcement each user has not had yet; the number of posts."""
    folder = directory or Config.ANNOUNCEMENTS_DIR
    if not folder.is_dir():
        return 0
    posted = 0
    for announcement in load_announcements(folder):
        day_end = datetime.combine(announcement.day + timedelta(days=1), time(), tzinfo=UTC)
        for user in db.users_joined_by(day_end):
            posted += _post(announcement, user)
    if posted:
        logger.info("Announcements posted", extra={"posts": posted})
    return posted


def _post(announcement: Announcement, user: User) -> int:
    """Post one announcement to one user (1), or nothing (0)."""
    if not db.claim_announcement(user.id, announcement.id):
        return 0
    lang = language_for(user)
    version = announcement.versions[lang]
    try:
        conv_id = db.whats_new_conversation_for_post(user.id, CHAT_TITLES[lang])
        db.add_message(conv_id, MessageRole.ASSISTANT, version.body, language=lang)
    except Exception:  # never fail startup: the next start tries again
        db.release_announcement(user.id, announcement.id)
        logger.warning(
            "Announcement not posted",
            extra={"user_id": user.id, "announcement": announcement.id},
            exc_info=True,
        )
        return 0
    send_push_to_user(
        user.id,
        f"{CHAT_TITLES[lang]}: {version.title}",
        _push_body(version),
        url=f"/#/conversations/{conv_id}",
        tag=f"whats-new-{announcement.id}",
    )
    return 1


def _push_body(version: Version) -> str:
    """The first line of text after the title, shortened."""
    lines = [line.strip() for line in version.body.splitlines()[1:] if line.strip()]
    text = lines[0] if lines else version.title
    return text if len(text) <= _PUSH_BODY_MAX_CHARS else text[: _PUSH_BODY_MAX_CHARS - 1] + "…"
