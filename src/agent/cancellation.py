"""Server-side Stop: cancel a running chat turn at the next checkpoint.

The stop route may land on a different gunicorn worker than the one running
the turn, so the request travels through kv_store (namespace ``cancel``,
keyed by conversation id - one active turn per conversation, like
interjections). The worker running the turn owns a CancelToken, registered
by request id (tools and graph nodes already know it via
get_current_request_id); a poller thread flips the token when the flag
appears. Checkpoints only read the token - no DB access on the hot path.
"""

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from src.agent.tool_results import get_current_request_id
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)

KV_NAMESPACE = "cancel"
STOP_REASON_USER = "user"
STOPPED_EMPTY_TEXT = "Stopped before answering."


class TurnCancelled(Exception):  # noqa: N818 - control flow, not an error
    """Raised at a checkpoint once the user pressed Stop."""


class CancelToken:
    """One turn's cancel state: an event plus kill callbacks run once."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[], None]] = []

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def add_callback(self, fn: Callable[[], None]) -> None:
        with self._lock:
            self._callbacks.append(fn)

    def remove_callback(self, fn: Callable[[], None]) -> None:
        with self._lock:
            if fn in self._callbacks:
                self._callbacks.remove(fn)

    def cancel(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            callbacks = list(self._callbacks)
        for fn in callbacks:
            try:
                fn()
            except Exception:
                logger.warning("Cancel callback failed", exc_info=True)


_tokens: dict[str, CancelToken] = {}
_tokens_lock = threading.Lock()


def register_token(request_id: str) -> CancelToken:
    token = CancelToken()
    with _tokens_lock:
        _tokens[request_id] = token
    return token


def unregister_token(request_id: str) -> None:
    with _tokens_lock:
        _tokens.pop(request_id, None)


def token_for(request_id: str) -> CancelToken | None:
    """The registered token of a request (deep-research subagents get their own)."""
    with _tokens_lock:
        return _tokens.get(request_id)


def _current_token() -> CancelToken | None:
    request_id = get_current_request_id()
    if request_id is None:
        return None
    with _tokens_lock:
        return _tokens.get(request_id)


def is_cancelled() -> bool:
    token = _current_token()
    return token is not None and token.cancelled


def raise_if_cancelled() -> None:
    if is_cancelled():
        raise TurnCancelled


class CancelOnToken(BaseCallbackHandler):
    """Abort a model call mid-stream once the turn is cancelled.

    LangGraph runs graph nodes on a background executor: when the consumer
    stops reading, closing the graph stream WAITS for the running node, so a
    model call would run (and bill) to completion. Raising from the token
    callback inside the node's thread ends the provider stream instead.
    """

    raise_error = True  # propagate instead of logging and continuing

    def on_llm_new_token(
        self,
        token: str | list[str | dict[str, Any]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        raise_if_cancelled()


@contextmanager
def on_cancel(fn: Callable[[], None]) -> Iterator[None]:
    """Run ``fn`` if the turn is cancelled while inside the block."""
    token = _current_token()
    if token is None:
        yield
        return
    token.add_callback(fn)
    try:
        yield
    finally:
        token.remove_callback(fn)


# The flag's VALUE names the turn (its assistant message id): an older turn
# of the same conversation that is still running server-side (its client
# aborted before the server acked it) must neither react to, nor clear, a
# Stop meant for the current turn - and a Stop sent after a turn ended can
# never match the next one.


def request_stop(user_id: str, conv_id: str, message_id: str) -> None:
    db.kv_set(user_id, KV_NAMESPACE, conv_id, message_id)


def stop_requested(user_id: str, conv_id: str, message_id: str) -> bool:
    return bool(db.kv_get(user_id, KV_NAMESPACE, conv_id) == message_id)


def clear_stop_request(user_id: str, conv_id: str, message_id: str) -> None:
    """Drop the flag if it is this turn's (another turn's Stop stays)."""
    try:
        if stop_requested(user_id, conv_id, message_id):
            db.kv_delete(user_id, KV_NAMESPACE, conv_id)
    except Exception:
        logger.debug("Stop flag clear failed", exc_info=True)


def run_poller(
    token: CancelToken,
    check: Callable[[], bool],
    done: threading.Event,
    interval_seconds: float,
) -> None:
    """Poll ``check`` until it is true (then cancel) or the turn ends."""
    while not done.wait(interval_seconds):
        try:
            if check():
                logger.info("Stop requested - cancelling turn")
                token.cancel()
                return
        except Exception:
            logger.warning("Stop flag poll failed", exc_info=True)
