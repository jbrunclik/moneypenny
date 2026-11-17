"""Memories that expire ("until Friday") and the text before the last change.

Nov 17 2026: "until Friday" stayed in the context until defrag noticed, and a
merge or rewrite that lost a detail could not be undone. valid_until ends a
memory after its last day (the nightly sweep moves it to Deleted, the model
stops seeing it at once); previous_content keeps the replaced text whoever
wrote it, and restoring swaps the two.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from src.agent.prompt_memory import get_user_memories_list_prompt
from src.agent.tools.context import set_conversation_context
from src.agent.tools.memory import manage_memory, search_memory
from src.utils.clock import local_today

if TYPE_CHECKING:
    from src.db.models import Database, User

TODAY = local_today()
TOMORROW = (TODAY + timedelta(days=1)).isoformat()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()


@pytest.fixture
def tool_db(
    test_database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> Generator[Database]:
    import src.agent.prompt_memory as prompt_memory
    import src.agent.tools.memory as memory_module

    monkeypatch.setattr(memory_module, "db", test_database)
    monkeypatch.setattr(prompt_memory, "db", test_database)
    set_conversation_context("conv-1", test_user.id)
    yield test_database
    set_conversation_context(None, None)


def _invoke(operations: list[dict[str, str]]) -> str:
    return str(manage_memory.invoke({"operations": operations}))


def _set_until(database: Database, memory_id: str, day: str) -> None:
    """Back-date an end date (the tool refuses past days)."""
    with database._pool.get_connection() as conn:
        conn.execute("UPDATE user_memories SET valid_until = ? WHERE id = ?", (day, memory_id))
        conn.commit()


class TestPreviousContent:
    def test_every_content_change_keeps_the_replaced_text(
        self, test_database: Database, test_user: User
    ) -> None:
        memory = test_database.add_memory(test_user.id, "Has a dog named Max")
        test_database.bulk_update_memories(test_user.id, [], [(memory.id, "Has a dog", "fact")], [])

        stored = test_database.get_memory(memory.id, test_user.id)
        assert stored is not None
        assert stored.previous_content == "Has a dog named Max"

    def test_restore_swaps_the_texts(self, test_database: Database, test_user: User) -> None:
        memory = test_database.add_memory(test_user.id, "Has a dog named Max")
        test_database.bulk_update_memories(test_user.id, [], [(memory.id, "Has a dog", "fact")], [])

        restored = test_database.restore_previous_memory(memory.id, test_user.id)

        assert restored is not None
        assert (restored.content, restored.previous_content) == (
            "Has a dog named Max",
            "Has a dog",
        )

    def test_nothing_to_restore(self, test_database: Database, test_user: User) -> None:
        memory = test_database.add_memory(test_user.id, "Never changed")
        assert test_database.restore_previous_memory(memory.id, test_user.id) is None


class TestExpirySweep:
    def test_past_memories_move_to_deleted(self, test_database: Database, test_user: User) -> None:
        ended = test_database.add_memory(test_user.id, "Away this week")
        _set_until(test_database, ended.id, YESTERDAY)
        today = test_database.add_memory(test_user.id, "Away until today")
        _set_until(test_database, today.id, TODAY.isoformat())
        kept = test_database.add_memory(test_user.id, "Has a dog")

        assert test_database.expire_memories(TODAY) == 1

        assert {m.id for m in test_database.list_memories(test_user.id)} == {today.id, kept.id}
        assert [m.id for m in test_database.list_deleted_memories(test_user.id)] == [ended.id]

    def test_protected_memories_never_expire(
        self, test_database: Database, test_user: User
    ) -> None:
        memory = test_database.add_memory(test_user.id, "Allergic to shellfish", protected=True)
        _set_until(test_database, memory.id, YESTERDAY)

        assert test_database.expire_memories(TODAY) == 0

    def test_a_restored_memory_loses_its_past_end_date(
        self, test_database: Database, test_user: User
    ) -> None:
        memory = test_database.add_memory(test_user.id, "Away this week")
        _set_until(test_database, memory.id, YESTERDAY)
        test_database.expire_memories(TODAY)

        assert test_database.restore_memory(memory.id, test_user.id)

        restored = test_database.get_memory(memory.id, test_user.id)
        assert restored is not None and restored.valid_until is None


class TestToolEndDates:
    def test_add_with_an_end_date(self, tool_db: Database, test_user: User) -> None:
        result = _invoke(
            [{"action": "add", "content": "Away in Vienna", "category": "context",
              "valid_until": TOMORROW}]
        )  # fmt: skip

        [memory] = tool_db.list_memories(test_user.id)
        assert memory.valid_until is not None and memory.valid_until.isoformat() == TOMORROW
        assert f"until {TOMORROW}" in result

    def test_patch_sets_and_clears_only_the_end_date(
        self, tool_db: Database, test_user: User
    ) -> None:
        memory = tool_db.add_memory(test_user.id, "On antibiotics")

        assert "until" in _invoke([{"action": "patch", "id": memory.id, "valid_until": TOMORROW}])
        assert "no end date" in _invoke([{"action": "patch", "id": memory.id, "valid_until": ""}])

        stored = tool_db.get_memory(memory.id, test_user.id)
        assert stored is not None
        assert (stored.content, stored.valid_until) == ("On antibiotics", None)

    @pytest.mark.parametrize(
        ("value", "reason"), [(YESTERDAY, "in the past"), ("next friday", "not a date")]
    )
    def test_bad_end_dates_are_rejected(
        self, tool_db: Database, test_user: User, value: str, reason: str
    ) -> None:
        result = _invoke(
            [{"action": "add", "content": "Away", "category": "context", "valid_until": value}]
        )

        assert reason in result
        assert tool_db.list_memories(test_user.id) == []

    def test_a_protected_memory_gets_no_end_date(self, tool_db: Database, test_user: User) -> None:
        memory = tool_db.add_memory(test_user.id, "Allergic to shellfish", protected=True)

        result = _invoke([{"action": "patch", "id": memory.id, "valid_until": TOMORROW}])

        assert "protected" in result
        stored = tool_db.get_memory(memory.id, test_user.id)
        assert stored is not None and stored.valid_until is None


class TestWhatTheModelSees:
    def test_the_list_shows_end_dates_and_hides_ended_memories(
        self, tool_db: Database, test_user: User
    ) -> None:
        dated = tool_db.add_memory(test_user.id, "Away in Vienna")
        _set_until(tool_db, dated.id, TOMORROW)
        ended = tool_db.add_memory(test_user.id, "Away last week")
        _set_until(tool_db, ended.id, YESTERDAY)

        prompt = get_user_memories_list_prompt(test_user.id)

        assert f"until {TOMORROW} | Away in Vienna" in prompt
        assert "Away last week" not in prompt
        assert "(1/" in prompt  # the count leaves the ended one out too

    def test_an_id_lookup_shows_the_previous_text(self, tool_db: Database, test_user: User) -> None:
        memory = tool_db.add_memory(test_user.id, "Has a dog named Max")
        tool_db.bulk_update_memories(test_user.id, [], [(memory.id, "Has a dog", "fact")], [])

        result = str(search_memory.invoke({"query": memory.id}))

        assert 'previous text: "Has a dog named Max"' in result
