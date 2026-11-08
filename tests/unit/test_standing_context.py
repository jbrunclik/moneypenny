"""What a standing chat (agent, sports or language program) adds to an
ordinary chat turn: its standing instructions, its data and its kv namespace."""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest

from src.api.helpers.standing_context import load_standing_context
from src.db.models import use_database

if TYPE_CHECKING:
    from src.db.models import Database, User


@pytest.fixture
def db(test_database: Database) -> Generator[Database]:
    with use_database(test_database):
        yield test_database


def _program(db: Database, user: User, namespace: str, program_id: str, name: str) -> object:
    db.kv_set(user.id, namespace, "programs", json.dumps([{"id": program_id, "name": name}]))
    return db.get_or_create_program_conversation(namespace, user.id, program_id)


def test_ordinary_chat_has_none(db: Database, test_user: User) -> None:
    conv = db.create_conversation(test_user.id, title="Plain chat")

    assert load_standing_context(conv, test_user) is None


def test_planner_has_none(db: Database, test_user: User) -> None:
    conv = db.get_or_create_planner_conversation(test_user.id)

    assert load_standing_context(conv, test_user) is None


def test_agent_chat(db: Database, test_user: User) -> None:
    agent = db.create_agent(
        test_user.id, "VWCE Watcher", system_prompt="Watch VWCE weekly", schedule="0 18 * * 5"
    )
    conv = db.get_conversation(agent.conversation_id or "", test_user.id)
    assert conv is not None

    standing = load_standing_context(conv, test_user)

    assert standing is not None
    assert (standing.kind, standing.name, standing.agent_id) == ("agent", "VWCE Watcher", agent.id)
    assert "Watch VWCE weekly" in standing.instructions
    assert "every Friday at 18:00" in standing.instructions
    assert standing.kv_namespace == f"agent:{agent.id}"


def test_system_briefing_uses_the_stock_prompt(db: Database, test_user: User) -> None:
    from src.agent.daily_briefing import SYSTEM_TYPE_DAILY_BRIEFING, resolve_agent_system_prompt

    agent = db.create_agent(
        test_user.id,
        "Daily Briefing",
        system_type=SYSTEM_TYPE_DAILY_BRIEFING,
        schedule="15 7 * * *",
    )
    conv = db.get_conversation(agent.conversation_id or "", test_user.id)
    assert conv is not None

    standing = load_standing_context(conv, test_user)

    stock = resolve_agent_system_prompt(agent)
    assert standing is not None and stock
    assert stock in standing.instructions


def test_sports_program(db: Database, test_user: User) -> None:
    conv = _program(db, test_user, "sports", "cycling", "Cycling")
    db.kv_set(test_user.id, "sports", "cycling:goals", '{"ftp": 260}')

    standing = load_standing_context(conv, test_user)  # type: ignore[arg-type]

    assert standing is not None
    assert (standing.kind, standing.name, standing.kv_namespace) == ("sports", "Cycling", "sports")
    assert "cycling:" in standing.instructions  # the real program id, not a placeholder
    assert "<program_id>" not in standing.instructions
    assert standing.data is not None and '"ftp": 260' in standing.data


def test_language_program(db: Database, test_user: User) -> None:
    conv = _program(db, test_user, "language", "italian", "Italian")

    standing = load_standing_context(conv, test_user)  # type: ignore[arg-type]

    assert standing is not None
    assert (standing.kind, standing.kv_namespace) == ("language", "language")
    assert "```quiz" in standing.instructions
    assert standing.data is not None and "No data stored yet" in standing.data


def test_a_program_missing_from_its_list_has_none(db: Database, test_user: User) -> None:
    conv = db.get_or_create_program_conversation("sports", test_user.id, "gone")

    assert load_standing_context(conv, test_user) is None
