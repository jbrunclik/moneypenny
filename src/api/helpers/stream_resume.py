"""Stream journal + resume-after-disconnect generator.

The producer journals every client-facing SSE event with a monotonic seq
(_StreamJournal); the resume endpoint replays rows after the client's last
seen seq and continues live (stream_resume_events). Persistence is
best-effort - journal failures never break the live stream.
"""

from __future__ import annotations

import json
import time
from collections.abc import Generator
from typing import Any

from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)


_JOURNALED_EVENT_TYPES = {
    "token",
    "thinking",
    "tool_start",
    "tool_end",
    "approval_required",
    "timeout",
}


class _StreamJournal:
    """Batched journal of stream events, keyed by assistant message id.

    Enables resume-after-disconnect: the producer journals every client-facing
    event with a monotonic seq; the resume endpoint replays rows after the
    client's last seen seq and continues live. Persistence is best-effort -
    journal failures never break the live stream.
    """

    def __init__(self, message_id: str) -> None:
        self.message_id = message_id
        self._seq = 0
        self._buffer: list[tuple[int, str]] = []
        self._last_flush = time.monotonic()
        try:
            db.journal_cleanup(Config.STREAM_JOURNAL_TTL_SECONDS)
        except Exception:
            logger.warning("Stream journal cleanup failed", exc_info=True)

    def record(self, event: dict[str, Any]) -> None:
        """Assign a seq to the event, buffer it, flush opportunistically."""
        self._seq += 1
        event["seq"] = self._seq
        try:
            serialized = json.dumps(event)
        except (TypeError, ValueError):
            serialized = json.dumps({"type": event.get("type", "unknown"), "seq": self._seq})
        self._buffer.append((self._seq, serialized))
        if (
            len(self._buffer) >= Config.STREAM_JOURNAL_FLUSH_EVENTS
            or time.monotonic() - self._last_flush >= Config.STREAM_JOURNAL_FLUSH_INTERVAL_SECONDS
        ):
            self.flush()

    def flush(self) -> None:
        buffer, self._buffer = self._buffer, []
        self._last_flush = time.monotonic()
        if not buffer:
            return
        try:
            db.journal_append_events(self.message_id, buffer)
        except Exception:
            logger.warning("Stream journal flush failed", exc_info=True)

    def finish(self) -> None:
        """Mark the stream as over (resume endpoint stops tailing on this)."""
        self._seq += 1
        self._buffer.append((self._seq, json.dumps({"type": "stream_end", "seq": self._seq})))
        self.flush()


def stream_resume_events(message_id: str, after_seq: int) -> Generator[str]:
    """Resume an interrupted chat stream from the event journal.

    Replays journaled events with seq > after_seq, then tails the journal
    until the producer's stream_end marker. After stream_end, waits for the
    saved message (the save happens in the consumer/cleanup thread shortly
    after the producer finishes) and emits a done event built from it.

    Works cross-worker: the journal is DB-backed, so the resume request may
    land on a different gunicorn worker than the one still generating.
    """
    deadline = time.monotonic() + Config.CHAT_TIMEOUT
    last_keepalive = time.monotonic()
    stream_ended = False
    save_grace_deadline: float | None = None
    # No new journal rows for this long (before stream_end) = the producer is
    # dead (e.g. process killed mid-turn left no terminal marker). Without
    # this bound a resume of a dead turn would hold a worker thread and send
    # keepalives until CHAT_TIMEOUT.
    stall_deadline = time.monotonic() + Config.STREAM_RESUME_STALL_SECONDS

    def _done_event_from_message(msg: Any) -> dict[str, Any]:
        done: dict[str, Any] = {
            "type": "done",
            "id": msg.id,
            "created_at": msg.created_at.isoformat(),
            "content": msg.content or "",
        }
        if msg.files:
            done["files"] = msg.files
        if msg.sources:
            done["sources"] = msg.sources
        if msg.generated_images:
            done["generated_images"] = msg.generated_images
        if msg.language:
            done["language"] = msg.language
        return done

    while time.monotonic() < deadline:
        events = db.journal_get_events(message_id, after_seq)
        if events:
            stall_deadline = time.monotonic() + Config.STREAM_RESUME_STALL_SECONDS
        for seq, event_json in events:
            after_seq = seq
            try:
                parsed = json.loads(event_json)
            except ValueError:
                continue
            if parsed.get("type") == "stream_end":
                stream_ended = True
                continue
            yield f"data: {event_json}\n\n"

        # A saved message (non-empty placeholder) means the turn is complete -
        # this also covers resume-after-completion when the journal was swept
        msg = db.get_message_by_id(message_id)
        if msg and (msg.content or msg.files):
            yield f"data: {json.dumps(_done_event_from_message(msg))}\n\n"
            return

        if stream_ended:
            if save_grace_deadline is None:
                save_grace_deadline = time.monotonic() + Config.STREAM_RESUME_SAVE_GRACE_SECONDS
            if msg is None or time.monotonic() > save_grace_deadline:
                # Placeholder deleted (failed turn) or the save never landed
                error_data = {
                    "type": "error",
                    "code": "RESUME_FAILED",
                    "message": "The response could not be recovered.",
                    "retryable": False,
                }
                yield f"data: {json.dumps(error_data)}\n\n"
                return

        if not stream_ended and time.monotonic() > stall_deadline:
            error_data = {
                "type": "error",
                "code": "RESUME_FAILED",
                "message": "The stream made no progress and appears to be dead.",
                "retryable": False,
            }
            yield f"data: {json.dumps(error_data)}\n\n"
            return

        if not events:
            time.sleep(0.4)
            if time.monotonic() - last_keepalive >= Config.SSE_KEEPALIVE_INTERVAL:
                yield ": keepalive\n\n"
                last_keepalive = time.monotonic()

    yield f"data: {json.dumps({'type': 'timeout'})}\n\n"
