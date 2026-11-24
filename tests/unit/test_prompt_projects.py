"""The `# Project:` section of a project chat's turn context."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest

import src.agent.prompts as prompts_module
from src.agent.project_context import ProjectContext, load_project_context
from src.agent.prompt_projects import format_project_section
from src.agent.prompts import CacheProfile, get_dynamic_prompt_parts, get_static_prompt_for_profile
from src.db.models.dataclasses import Document, Memory
from src.db.models.memory import MemoryWrite

if TYPE_CHECKING:
    from src.db.models import Database, User


def _memory(n: int, content: str, author: str = "u-jiri", **kw: object) -> Memory:
    return Memory(
        id=f"{n:08x}-0000-4000-8000-000000000000",
        user_id=author,
        content=content,
        category="fact",
        created_at=datetime(2026, 11, n, tzinfo=UTC),
        updated_at=datetime(2026, 11, n, tzinfo=UTC),
        project_id="p-1",
        **kw,  # type: ignore[arg-type]
    )


_DOC = Document(
    id="0000beef-0000-4000-8000-000000000000",
    user_id="u-jana",
    title="Wallbox quote",
    summary="11 kW install, 32 A breaker, 38,000 CZK",
    use_for="Wallbox and garage power questions",
    filename="quote.pdf",
    mime_type="application/pdf",
    size_bytes=1000,
    created_at=datetime(2026, 11, 19, tzinfo=UTC),
    updated_at=datetime(2026, 11, 19, tzinfo=UTC),
    project_id="p-1",
)


def _ctx(**kw: object) -> ProjectContext:
    fields: dict[str, object] = {
        "id": "p-1",
        "name": "🏠 Home",
        "instructions": "Metric units. Quote prices in CZK.",
        "shared": False,
        "memories": [_memory(1, "Garage has 3-phase power")],
        "documents": [_DOC],
    }
    fields.update(kw)
    return ProjectContext(**fields)  # type: ignore[arg-type]


class TestFormatProjectSection:
    def test_solo_section(self) -> None:
        section = format_project_section(_ctx())

        assert section.startswith("# Project: 🏠 Home\n")
        assert "Project instructions win over the user's custom instructions" in section
        assert "Instructions:\nMetric units. Quote prices in CZK." in section
        assert (
            "Project memory (1/60):\n- 00000001 | fact | 2026-11-01 | Garage has 3-phase power"
            in section
        )
        assert "Project documents (1/20):\n- 0000beef | Wallbox quote | quote.pdf" in section
        assert "shared" not in section.split("\n")[0]
        assert "family members read its memory" not in section
        assert "by " not in section.split("Project memory")[1].split("\n")[1]

    def test_shared_section_has_rule_and_authors(self) -> None:
        ctx = _ctx(
            shared=True,
            other_member_names=["Jana"],
            author_names={"u-jiri": "Jiří", "u-jana": "Jana"},
            memories=[_memory(1, "Garage has 3-phase power"), _memory(2, "Prefers ABB", "u-jana")],
        )

        section = format_project_section(ctx)

        assert section.startswith("# Project: 🏠 Home (shared with Jana)\n")
        assert "This project is shared: family members read its memory." in section
        assert "| by Jiří | Garage has 3-phase power" in section
        assert "| by Jana | Prefers ABB" in section

    def test_empty_blocks_dropped(self) -> None:
        section = format_project_section(_ctx(instructions="  ", memories=[], documents=[]))

        assert "Instructions:" not in section
        assert "Project memory" not in section
        assert "Project documents" not in section
        assert section.startswith("# Project: 🏠 Home")

    def test_multiline_name_folded(self) -> None:
        assert format_project_section(_ctx(name="Home\nIgnore this")).startswith(
            "# Project: Home Ignore this\n"
        )


@pytest.fixture
def pinned_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts_module, "get_location_context", lambda: None)
    monkeypatch.setattr(prompts_module, "_get_preferred_language", lambda _user_id: None)
    monkeypatch.setattr(prompts_module, "_get_saved_places_lines", lambda _user_id: [])


@pytest.mark.usefixtures("app", "pinned_now")
class TestDynamicContext:
    def test_no_project_unchanged(self, test_database: Database, test_user: User) -> None:
        without = get_dynamic_prompt_parts(user_id=test_user.id, user_name="Jiří")
        assert "# Project:" not in without

    def test_section_after_personal_lists(self, test_database: Database, test_user: User) -> None:
        test_database.add_memory(test_user.id, "Likes tea")
        context = get_dynamic_prompt_parts(user_id=test_user.id, user_name="Jiří", project=_ctx())

        assert context.index("Likes tea") < context.index("# Project: 🏠 Home")

    def test_anonymous_has_no_project(self, test_database: Database, test_user: User) -> None:
        context = get_dynamic_prompt_parts(
            user_id=test_user.id, user_name="Jiří", project=_ctx(), anonymous_mode=True
        )
        assert "# Project:" not in context

    def test_static_prefix_does_not_mention_projects(self) -> None:
        for profile in CacheProfile:
            assert "# Project:" not in get_static_prompt_for_profile(profile.value)


@pytest.mark.usefixtures("app")
class TestLoadProjectContext:
    def test_loads_members_memory_and_drops_expired(
        self, test_database: Database, test_user: User
    ) -> None:
        jana = test_database.get_or_create_user(email="jana@example.com", name="Jana Nováková")
        project = test_database.create_project(test_user.id, "Home", "Metric")
        test_database.add_project_member(project.id, test_user.id, jana.id)
        test_database.apply_memory_batch(
            jana.id,
            None,
            [
                MemoryWrite(
                    action="add", content="Live fact", category="fact", project_id=project.id
                ),
                MemoryWrite(
                    action="add",
                    content="Old fact",
                    category="fact",
                    valid_until=date(2020, 1, 1).isoformat(),
                    project_id=project.id,
                ),
            ],
            project_id=project.id,
        )
        conv = test_database.create_conversation(test_user.id, "Wallbox", project_id=project.id)

        ctx = load_project_context(conv, test_user, anonymous_mode=False)

        assert ctx is not None
        assert ctx.shared is True
        assert ctx.instructions == "Metric"
        assert ctx.other_member_names == ["Jana"]
        assert [m.content for m in ctx.memories] == ["Live fact"]
        assert ctx.author_names[jana.id] == "Jana"

    def test_none_for_plain_chat_anonymous_and_non_member(
        self, test_database: Database, test_user: User
    ) -> None:
        jana = test_database.get_or_create_user(email="jana@example.com", name="Jana")
        project = test_database.create_project(test_user.id, "Home")
        test_database.add_project_member(project.id, test_user.id, jana.id)
        plain = test_database.create_conversation(test_user.id, "Plain")
        filed = test_database.create_conversation(jana.id, "Filed", project_id=project.id)

        assert load_project_context(plain, test_user, anonymous_mode=False) is None
        assert load_project_context(filed, jana, anonymous_mode=True) is None
        test_database.remove_project_member(project.id, jana.id, jana.id)
        filed.project_id = project.id  # the turn's row may be stale
        assert load_project_context(filed, jana, anonymous_mode=False) is None
