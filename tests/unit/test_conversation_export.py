"""A conversation as a Markdown file (src/api/helpers/conversation_export.py)."""

from datetime import UTC, datetime

from src.api.helpers.conversation_export import content_disposition, conversation_markdown
from src.db.models.dataclasses import Message
from src.enums import MessageRole

_AT = datetime(2026, 11, 14, 18, 35, tzinfo=UTC)


def _msg(role: MessageRole, content: str, **extra: object) -> Message:
    return Message(
        id=f"m-{len(content)}-{role.value}",
        conversation_id="c1",
        role=role,
        content=content,
        created_at=_AT,
        **extra,  # type: ignore[arg-type]
    )


def test_title_roles_times_and_content_verbatim() -> None:
    code = "```python\nprint('hi')\n```"
    md = conversation_markdown(
        "Rear light",
        [
            _msg(MessageRole.USER, "Which mount?"),
            _msg(MessageRole.ASSISTANT, f"Use this:\n\n{code}"),
        ],
        exported_at=_AT,
    )

    assert md.startswith("# Rear light\n")
    assert "**You**" in md and "**Moneypenny**" in md
    assert "2026-11-14 19:35" in md  # local time (Europe/Prague)
    assert code in md  # code blocks untouched
    assert md.index("Which mount?") < md.index("Use this:")


def test_attachments_sources_and_artifacts_are_listed_by_name() -> None:
    md = conversation_markdown(
        "Trip",
        [
            _msg(
                MessageRole.USER, "Plan it", files=[{"name": "map.pdf", "type": "application/pdf"}]
            ),
            _msg(
                MessageRole.ASSISTANT,
                "Here",
                sources=[{"title": "Mapy", "url": "https://mapy.com"}],
                artifacts=[{"id": "a1", "version": 1, "title": "Packing list"}],
            ),
        ],
        exported_at=_AT,
    )

    assert "Attachments: map.pdf" in md
    assert "- [Mapy](https://mapy.com)" in md
    assert "Artifact: Packing list" in md


def test_an_empty_reply_placeholder_is_left_out() -> None:
    md = conversation_markdown(
        "T", [_msg(MessageRole.USER, "Hi"), _msg(MessageRole.ASSISTANT, "")], exported_at=_AT
    )
    assert "**Moneypenny**" not in md


def test_a_czech_title_downloads_under_its_own_name() -> None:
    header = content_disposition("Zadní světlo: montáž", _AT)

    assert header.startswith('attachment; filename="')
    assert "filename*=UTF-8''" in header
    assert "Zadn%C3%AD" in header
    assert header.split('filename="', 1)[1].split('"', 1)[0].isascii()
    assert ":" not in header.split("filename*=", 1)[1]
