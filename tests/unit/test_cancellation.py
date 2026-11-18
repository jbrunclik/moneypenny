"""Unit tests for turn cancellation (src/agent/cancellation.py)."""

import threading

import pytest

from src.agent import cancellation
from src.agent.cancellation import CancelToken, TurnCancelled
from src.agent.tool_results import set_current_request_id


@pytest.fixture(autouse=True)
def _request_scope():
    set_current_request_id("req-1")
    yield
    cancellation.unregister_token("req-1")
    set_current_request_id(None)


def test_is_cancelled_without_a_registered_token_is_false() -> None:
    assert cancellation.is_cancelled() is False
    cancellation.raise_if_cancelled()  # no-op


def test_cancel_flips_the_current_token() -> None:
    token = cancellation.register_token("req-1")
    token.cancel()
    assert cancellation.is_cancelled() is True
    with pytest.raises(TurnCancelled):
        cancellation.raise_if_cancelled()


def test_callbacks_run_once_on_cancel() -> None:
    token = CancelToken()
    calls: list[int] = []
    token.add_callback(lambda: calls.append(1))
    token.cancel()
    token.cancel()
    assert calls == [1]


def test_a_failing_callback_does_not_block_the_others() -> None:
    token = CancelToken()
    calls: list[str] = []

    def boom() -> None:
        raise RuntimeError("kill failed")

    token.add_callback(boom)
    token.add_callback(lambda: calls.append("second"))
    token.cancel()
    assert calls == ["second"]


def test_on_cancel_registers_only_for_the_block() -> None:
    token = cancellation.register_token("req-1")
    calls: list[str] = []
    with cancellation.on_cancel(lambda: calls.append("inside")):
        pass
    token.cancel()
    assert calls == []


def test_on_cancel_fires_while_inside_the_block() -> None:
    token = cancellation.register_token("req-1")
    calls: list[str] = []
    with cancellation.on_cancel(lambda: calls.append("inside")):
        token.cancel()
    assert calls == ["inside"]


def test_poller_cancels_when_the_check_turns_true() -> None:
    token = CancelToken()
    done = threading.Event()
    answers = iter([False, True])
    thread = threading.Thread(
        target=cancellation.run_poller,
        args=(token, lambda: next(answers), done, 0.01),
    )
    thread.start()
    thread.join(timeout=2)
    assert token.cancelled is True
    assert not thread.is_alive()


def test_poller_exits_when_the_turn_ends() -> None:
    token = CancelToken()
    done = threading.Event()
    thread = threading.Thread(
        target=cancellation.run_poller, args=(token, lambda: False, done, 0.01)
    )
    thread.start()
    done.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert token.cancelled is False


def test_poller_survives_a_failing_check() -> None:
    token = CancelToken()
    done = threading.Event()
    answers = iter([RuntimeError("db locked"), True])

    def check() -> bool:
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    thread = threading.Thread(target=cancellation.run_poller, args=(token, check, done, 0.01))
    thread.start()
    thread.join(timeout=2)
    assert token.cancelled is True


def test_a_pending_stop_expires(monkeypatch: pytest.MonkeyPatch, test_database: object) -> None:
    """A Stop for a send that never reached the server must not stop its retry
    minutes later."""
    from src.db.models import Database, use_database

    assert isinstance(test_database, Database)
    with use_database(test_database):
        user = test_database.get_or_create_user("u@example.com", "U")
        cancellation.request_stop_by_client_id(user.id, "conv-1", "client-1")
        monkeypatch.setattr(cancellation, "PENDING_STOP_TTL_SECONDS", -1)
        assert not cancellation.adopt_pending_stop(user.id, "conv-1", "client-1", "reply-1")


def test_stale_stop_flags_are_swept(test_database: object) -> None:
    """A Stop that lands after its turn ended has no turn left to clear it:
    the next turn's sweep drops it once it is older than any turn."""
    from src.db.models import Database, use_database

    assert isinstance(test_database, Database)
    with use_database(test_database):
        user = test_database.get_or_create_user("u@example.com", "U")
        cancellation.request_stop(user.id, "late", "reply-old")
        cancellation.request_stop_by_client_id(user.id, "late", "client-old")
        cancellation.request_finish_now(user.id, "late", "reply-old")
        with test_database._pool.get_connection() as conn:
            conn.execute("UPDATE kv_store SET updated_at = '2026-01-01T00:00:00+00:00'")
            conn.commit()
        cancellation.request_stop(user.id, "running", "reply-now")

        assert cancellation.sweep_stale_flags(user.id) == 3

        assert test_database.kv_get(user.id, cancellation.KV_NAMESPACE, "running") == "reply-now"
        assert test_database.kv_get(user.id, cancellation.KV_NAMESPACE, "late") is None
