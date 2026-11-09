"""What's new: announcements from repo files, posted once per user into a
read-only chat in the user's language, with a push (docs/features/whats-new.md)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from src.db.models import use_database
from src.services.announcements import (
    AnnouncementError,
    load_announcements,
    parse_announcement,
    post_pending_announcements,
    revise_posted_announcements,
)

if TYPE_CHECKING:
    from pathlib import Path

    from src.db.models import Conversation, Database, User

_TEXT = """<!-- lang: cs -->
# Agenti, kteří se ozvou sami
Nově si agenta založíte v chatu.

<!-- lang: en -->
# Agents that check in on their own
You can now set up an agent by talking.
"""


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    (tmp_path / "2099-01-01-agents.md").write_text(_TEXT)
    return tmp_path


@pytest.fixture
def db(test_database: Database) -> Iterator[Database]:
    with use_database(test_database):
        yield test_database


@pytest.fixture
def push() -> Iterator[MagicMock]:
    with patch("src.services.announcements.send_push_to_user") as mock:
        yield mock


def _whats_new(db: Database, user: User) -> list[Conversation]:
    """The user's live (not trashed) What's new chat, as a list of 0 or 1."""
    chat = db.get_whats_new_conversation(user.id)
    return [chat] if chat else []


def test_parse_reads_both_languages(folder: Path) -> None:
    announcement = parse_announcement(folder / "2099-01-01-agents.md")

    assert announcement.id == "2099-01-01-agents"
    assert announcement.versions["cs"].title == "Agenti, kteří se ozvou sami"
    assert announcement.versions["en"].body.startswith("## Agents that check in")


def test_parse_refuses_a_missing_language(tmp_path: Path) -> None:
    path = tmp_path / "2099-01-02-half.md"
    path.write_text("<!-- lang: cs -->\n# Jen česky\nText.\n")

    with pytest.raises(AnnouncementError, match="en"):
        parse_announcement(path)


def test_an_invalid_file_is_skipped(folder: Path) -> None:
    (folder / "2099-01-02-half.md").write_text("no languages here")

    assert [a.id for a in load_announcements(folder)] == ["2099-01-01-agents"]


def test_post_creates_the_chat_in_the_users_language(
    db: Database, test_user: User, folder: Path, push: MagicMock
) -> None:
    english = db.get_or_create_user(email="en@example.com", name="En")
    db.update_user_preferred_language(english.id, "English")

    assert post_pending_announcements(folder) == 2

    [cs_chat] = _whats_new(db, test_user)
    [en_chat] = _whats_new(db, english)
    cs_message = db.get_messages(cs_chat.id)[-1]
    assert (cs_chat.title, cs_message.role, cs_message.language) == ("Novinky", "assistant", "cs")
    assert "Nově si agenta" in cs_message.content
    assert en_chat.title == "What's new"
    assert "by talking" in db.get_messages(en_chat.id)[-1].content


def test_post_is_once_per_user(
    db: Database, test_user: User, folder: Path, push: MagicMock
) -> None:
    post_pending_announcements(folder)

    assert post_pending_announcements(folder) == 0
    [chat] = _whats_new(db, test_user)
    assert len(db.get_messages(chat.id)) == 1


def test_a_new_announcement_lands_in_the_same_chat(
    db: Database, test_user: User, folder: Path, push: MagicMock
) -> None:
    post_pending_announcements(folder)
    (folder / "2099-01-03-more.md").write_text(_TEXT.replace("Agenti", "Další"))

    post_pending_announcements(folder)

    [chat] = _whats_new(db, test_user)
    assert len(db.get_messages(chat.id)) == 2


def test_an_archived_chat_comes_back(
    db: Database, test_user: User, folder: Path, push: MagicMock
) -> None:
    post_pending_announcements(folder)
    [chat] = _whats_new(db, test_user)
    db.archive_conversation(chat.id, test_user.id)
    (folder / "2099-01-03-more.md").write_text(_TEXT)

    post_pending_announcements(folder)

    again = db.get_conversation(chat.id, test_user.id)
    assert again is not None and not again.archived
    assert len(db.get_messages(chat.id)) == 2


def test_a_deleted_chat_is_recreated_with_only_the_new_post(
    db: Database, test_user: User, folder: Path, push: MagicMock
) -> None:
    post_pending_announcements(folder)
    [old] = _whats_new(db, test_user)
    db.trash_conversation(old.id, test_user.id)
    (folder / "2099-01-03-more.md").write_text(_TEXT)

    post_pending_announcements(folder)

    [new] = _whats_new(db, test_user)
    assert new.id != old.id
    assert len(db.get_messages(new.id)) == 1


def test_a_user_who_joined_later_gets_no_backlog(
    db: Database, test_user: User, tmp_path: Path, push: MagicMock
) -> None:
    (tmp_path / "2020-01-01-old.md").write_text(_TEXT)

    assert post_pending_announcements(tmp_path) == 0
    assert _whats_new(db, test_user) == []


def test_each_post_pushes_with_a_link_to_the_chat(
    db: Database, test_user: User, folder: Path, push: MagicMock
) -> None:
    post_pending_announcements(folder)

    [chat] = _whats_new(db, test_user)
    user_id, title, _body = push.call_args.args
    assert (user_id, title) == (test_user.id, "Novinky: Agenti, kteří se ozvou sami")
    assert push.call_args.kwargs["url"] == f"/#/conversations/{chat.id}"
    assert push.call_args.kwargs["tag"] == "whats-new-2099-01-01-agents"


def test_a_failed_post_is_tried_again_next_time(
    db: Database, test_user: User, folder: Path, push: MagicMock
) -> None:
    with patch.object(db, "add_message", side_effect=RuntimeError("disk full")):
        assert post_pending_announcements(folder) == 0

    assert post_pending_announcements(folder) == 1


@pytest.mark.parametrize("apply_migrations", [True, False])
def test_startup_posts_only_where_migrations_apply(apply_migrations: bool) -> None:
    """Gunicorn workers and `make run` post; tests, timers and scripts never do."""
    from src import app as app_module

    with (
        patch.object(app_module.Config, "is_testing", return_value=False),
        patch.object(app_module.Config, "validate", return_value=[]),
        patch.object(app_module.db, "migrate"),
        patch.object(app_module, "post_pending_announcements") as post,
        patch.object(app_module, "install_memory_profiler"),
        patch.object(app_module, "start_malloc_trimmer"),
    ):
        app_module._prepare_process(MagicMock(), apply_migrations=apply_migrations)

    assert post.called is apply_migrations


def test_a_posting_failure_never_stops_startup() -> None:
    from src import app as app_module

    with (
        patch.object(app_module.db, "migrate"),
        patch.object(app_module, "post_pending_announcements", side_effect=RuntimeError("x")),
        patch.object(app_module, "install_memory_profiler"),
        patch.object(app_module, "start_malloc_trimmer"),
    ):
        app_module._prepare_process(MagicMock(), apply_migrations=True)


def test_every_repo_announcement_is_valid() -> None:
    """A malformed announcement file would be skipped at deploy: fail here instead."""
    from src.config import Config

    files = sorted(Config.ANNOUNCEMENTS_DIR.glob("*.md"))
    assert files, "announcements/ holds the What's new posts"
    for path in files:
        parse_announcement(path)  # raises AnnouncementError with the reason


def test_testing_never_posts() -> None:
    """`make openapi` (FLASK_ENV=testing, inside `make lint`) creates the app with
    migrations on: it must not post into the local database."""
    from src import app as app_module

    with (
        patch.object(app_module.db, "migrate"),
        patch.object(app_module, "post_pending_announcements") as post,
        patch.object(app_module, "install_memory_profiler"),
        patch.object(app_module, "start_malloc_trimmer"),
    ):
        app_module._prepare_process(MagicMock(), apply_migrations=True)

    assert not post.called


def test_an_edited_announcement_revises_the_posted_text_quietly(
    db: Database, test_user: User, folder: Path, push: MagicMock
) -> None:
    post_pending_announcements(folder)
    [chat] = _whats_new(db, test_user)
    before = db.get_conversation(chat.id, test_user.id)
    (folder / "2099-01-01-agents.md").write_text(_TEXT.replace("Nově si", "Teď si"))
    push.reset_mock()

    assert post_pending_announcements(folder) == 0

    [message] = db.get_messages(chat.id)
    assert "Teď si agenta" in message.content
    push.assert_not_called()
    after = db.get_conversation(chat.id, test_user.id)
    assert before is not None and after is not None
    assert after.updated_at == before.updated_at  # the chat does not jump to the top


def test_an_unchanged_announcement_is_not_rewritten(
    db: Database, test_user: User, folder: Path, push: MagicMock
) -> None:
    post_pending_announcements(folder)

    assert revise_posted_announcements(folder) == 0


def test_a_revision_skips_a_deleted_post(
    db: Database, test_user: User, folder: Path, push: MagicMock
) -> None:
    post_pending_announcements(folder)
    [chat] = _whats_new(db, test_user)
    db.delete_conversation(chat.id, test_user.id)
    (folder / "2099-01-01-agents.md").write_text(_TEXT.replace("Nově si", "Teď si"))

    assert revise_posted_announcements(folder) == 0
