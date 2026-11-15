"""Which fixed prefix a model call sent, and how long since anyone sent it:
the data that decides per-user tool sets (they would split the prefix the
users share - docs/superpowers/specs/2026-11-15-cost-telemetry-design.md)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from src.agent import prefix_cache
from src.agent.prefix_cache import note_prefix_sent, prefix_key
from src.db.models import use_database

if TYPE_CHECKING:
    from src.db.models import Database


@pytest.fixture(autouse=True)
def _db(test_database: Database) -> Iterator[None]:
    with use_database(test_database):
        yield


def test_the_key_is_short_and_stable() -> None:
    key = prefix_key("gemini-4-hydrogen", "You are Moneypenny.", "[{'name': 'todoist'}]")
    assert key == prefix_key("gemini-4-hydrogen", "You are Moneypenny.", "[{'name': 'todoist'}]")
    assert len(key) == 8


@pytest.mark.parametrize(
    "other",
    [
        ("gemini-4-carbon", "You are Moneypenny.", "[{'name': 'todoist'}]"),
        ("gemini-4-hydrogen", "You are Moneypenny!", "[{'name': 'todoist'}]"),
        ("gemini-4-hydrogen", "You are Moneypenny.", "[]"),
    ],
)
def test_any_part_changes_the_key(other: tuple[str, str, str]) -> None:
    assert prefix_key(*other) != prefix_key(
        "gemini-4-hydrogen", "You are Moneypenny.", "[{'name': 'todoist'}]"
    )


def test_the_gap_and_who_sent_it_last() -> None:
    assert note_prefix_sent("abcd1234", "user-a", 1000.0) == (None, None)
    assert note_prefix_sent("abcd1234", "user-b", 1030.0) == (30.0, False)
    assert note_prefix_sent("abcd1234", "user-b", 1031.5) == (1.5, True)
    assert note_prefix_sent("ffff0000", "user-b", 1032.0) == (None, None)


def test_a_store_failure_gives_no_gap_and_no_error() -> None:
    with patch.object(prefix_cache.db, "kv_get", side_effect=RuntimeError("locked")):
        assert note_prefix_sent("abcd1234", "user-a", 1000.0) == (None, None)
