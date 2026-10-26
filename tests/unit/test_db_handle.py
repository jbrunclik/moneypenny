"""The global ``db`` handle (src/db/models): it stands in for whichever
Database is current, so a patch made through it must land on that Database
and never outlive it."""

from unittest.mock import MagicMock

import pytest

from src.db.models import db, set_database


def test_a_monkeypatch_through_db_does_not_outlive_its_database() -> None:
    first, second = MagicMock(), MagicMock()
    previous = set_database(first)
    try:
        # monkeypatch undoes a patch by writing back what it read: a bound
        # method of `first`, which then shadowed every later database
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(db, "delete_message_by_id", lambda _mid: None)
        set_database(second)
        db.delete_message_by_id("m1")
    finally:
        set_database(previous)
    second.delete_message_by_id.assert_called_once_with("m1")
    first.delete_message_by_id.assert_not_called()


def test_attribute_writes_reach_the_current_database() -> None:
    target = MagicMock()
    previous = set_database(target)
    try:
        db.some_flag = True  # type: ignore[attr-defined]
        assert target.some_flag is True
        del db.some_flag  # type: ignore[attr-defined]
        assert "some_flag" not in vars(target)
    finally:
        set_database(previous)
