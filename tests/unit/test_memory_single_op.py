"""apply_single_op: one memory write through the tool's guards (background review)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.agent.tools.memory import apply_single_op
from src.config import Config

if TYPE_CHECKING:
    from src.db.models import Database, User


@pytest.fixture
def mem_db(test_database: Database, monkeypatch: pytest.MonkeyPatch) -> Database:
    import src.agent.tools.memory as memory_module

    monkeypatch.setattr(memory_module, "db", test_database)
    return test_database


def test_apply_single_op_applies_valid_and_rejects_bad(mem_db: Database, test_user: User) -> None:
    existing = mem_db.add_memory(test_user.id, "Ema - ballet on Mondays", "fact")

    bad = apply_single_op(
        test_user.id,
        None,
        {"action": "patch", "id": existing.id, "old_text": "Fridays", "new_text": "Tuesdays"},
    )
    good = apply_single_op(
        test_user.id, None, {"action": "add", "content": "Owns a beagle", "category": "fact"}
    )

    assert bad is None
    assert good == "Owns a beagle"
    assert {m.content for m in mem_db.list_memories(test_user.id)} == {
        "Ema - ballet on Mondays",
        "Owns a beagle",
    }


def test_apply_single_op_patch_returns_new_text(mem_db: Database, test_user: User) -> None:
    existing = mem_db.add_memory(test_user.id, "Ema - ballet on Mondays", "fact")

    result = apply_single_op(
        test_user.id,
        None,
        {"action": "patch", "id": existing.id, "old_text": "Mondays", "new_text": "Tuesdays"},
    )

    assert result == "Ema - ballet on Tuesdays"


def test_apply_single_op_full_bank_rejects_add_allows_patch(
    mem_db: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Config, "MEMORY_MAX_ENTRIES", 1)
    existing = mem_db.add_memory(test_user.id, "Ema - ballet on Mondays", "fact")

    added = apply_single_op(
        test_user.id, None, {"action": "add", "content": "Owns a beagle", "category": "fact"}
    )
    patched = apply_single_op(
        test_user.id,
        None,
        {"action": "patch", "id": existing.id, "old_text": "Mondays", "new_text": "Tuesdays"},
    )

    assert added is None
    assert patched == "Ema - ballet on Tuesdays"


def test_apply_single_op_never_deletes(mem_db: Database, test_user: User) -> None:
    existing = mem_db.add_memory(test_user.id, "Ema - ballet on Mondays", "fact")

    assert apply_single_op(test_user.id, None, {"action": "delete", "id": existing.id}) is None
    assert len(mem_db.list_memories(test_user.id)) == 1


def test_apply_single_op_skips_an_add_the_bank_already_holds(
    mem_db: Database, test_user: User
) -> None:
    mem_db.add_memory(test_user.id, "Ema - ballet on Tuesdays", "fact")

    result = apply_single_op(
        test_user.id,
        None,
        {"action": "add", "content": " ema -  Ballet on tuesdays. ", "category": "fact"},
    )

    assert result is None
    assert len(mem_db.list_memories(test_user.id)) == 1
