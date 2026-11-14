"""Steering saved for a turn in flight (src/agent/interjection.py)."""

import threading
from collections.abc import Iterator

import pytest

from src.agent.interjection import pop_interjection, save_interjection
from src.db.models import Database, User, use_database


@pytest.fixture
def db(test_database: Database) -> Iterator[Database]:
    with use_database(test_database):
        yield test_database


def test_two_quick_messages_both_reach_the_turn(db: Database, test_user: User) -> None:
    """The slot held one message: a second steering send before the next tool
    round replaced the first, which the turn then never read."""
    save_interjection(test_user.id, "conv-1", "use the 2025 numbers")
    save_interjection(test_user.id, "conv-1", "and in Czech")

    assert pop_interjection(test_user.id, "conv-1") == "use the 2025 numbers\n\nand in Czech"
    assert pop_interjection(test_user.id, "conv-1") is None


def test_steering_saved_while_a_pop_runs_is_never_lost(db: Database, test_user: User) -> None:
    """A pop is one statement: nothing saved between its read and its delete."""
    saved = [f"msg {i}" for i in range(40)]
    popped: list[str] = []
    done = threading.Event()

    def pop_until_done() -> None:
        while not done.is_set():
            if text := pop_interjection(test_user.id, "conv-1"):
                popped.extend(text.split("\n\n"))

    import contextvars

    popper = threading.Thread(target=contextvars.copy_context().run, args=(pop_until_done,))
    popper.start()
    for text in saved:
        save_interjection(test_user.id, "conv-1", text)
    done.set()
    popper.join()
    if rest := pop_interjection(test_user.id, "conv-1"):
        popped.extend(rest.split("\n\n"))

    assert sorted(popped) == sorted(saved)


def test_a_burst_keeps_only_the_newest_steering(
    db: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agent import interjection

    monkeypatch.setattr(interjection, "INTERJECTION_MAX_CHARS", 20)
    for i in range(10):
        save_interjection(test_user.id, "conv-1", f"message {i}")

    kept = pop_interjection(test_user.id, "conv-1")
    assert kept is not None and len(kept) <= 20
    assert kept.endswith("message 9")
