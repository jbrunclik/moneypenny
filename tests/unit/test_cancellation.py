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
