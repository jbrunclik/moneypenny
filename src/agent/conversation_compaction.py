"""Non-destructive compaction for regular (non-agent) conversations.

Long chats re-send their entire history to the LLM every turn, so cost grows
~O(n^2) over a conversation. This module bounds the history *sent to the model*
by replacing older turns with a running summary while keeping recent turns
verbatim. The summary is a list of segments, each summarizing one batch of
messages from full text (see ``compaction_segments.py``).

Unlike the autonomous-agent path in ``compaction.py``, this is **non-destructive**:
the full message history stays in the database for display. Only the enriched
history handed to the agent is compacted, and the running summary is persisted
in ``kv_store`` (DB-backed, safe across the 4 gunicorn workers) so it is
recomputed only every few turns instead of on every request.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from src.agent.compaction_segments import Segment, extend_segments, max_passes, render_segments
from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Conversations with a background summary refresh in flight (process-local;
# two workers refreshing the same conversation is wasteful once, not wrong -
# the persisted state is last-write-wins in kv_store)
_inflight_lock = threading.Lock()
_inflight_refreshes: set[str] = set()

# kv_store namespace for persisted per-conversation running summaries
KV_NAMESPACE = "conv_compaction"

# Prefix marking the synthetic summary message so the model treats it as context
SUMMARY_PREFIX = "[Summary of earlier conversation]"

# Closes the summary message: the summary keeps the gist, not every detail,
# and search_conversations covers this conversation's summarized messages
SUMMARY_RECALL_HINT = (
    "[The messages above were condensed into this summary, so exact details "
    "(numbers, names, wording) may be missing. If you need one and the "
    "search_conversations tool is available, search for it - it includes this "
    "conversation's summarized messages.]"
)

# Failed refreshes back off exponentially (30 min, 1 h, 2 h, ... up to 1 day)
_FAILURE_BACKOFF_BASE_SECONDS = 30 * 60
_FAILURE_BACKOFF_MAX_SECONDS = 24 * 60 * 60

# Rough chars-per-token for history size estimation. Deliberately conservative
# (Gemini averages ~4 for English, ~3 for Czech) so the token trigger fires
# early rather than late.
_CHARS_PER_TOKEN_ESTIMATE = 3

# The recent tail kept verbatim never shrinks below this many messages, even
# when the tail alone exceeds the token threshold - the model needs some
# verbatim context to continue the conversation coherently.
_MIN_KEEP_RECENT = 4


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate LLM tokens for enriched history messages (content only)."""
    chars = sum(len(m.get("content") or "") for m in messages)
    return chars // _CHARS_PER_TOKEN_ESTIMATE


@dataclass(frozen=True)
class _State:
    """Persisted segmented running summary for one conversation."""

    segments: tuple[Segment, ...] = ()
    # Legacy single-summary state (pre-segments): served as one segment until
    # the next refresh rebuilds it from full text
    legacy: bool = False
    # Legacy states never tracked passes; theirs is an upper-bound estimate
    generation_estimated: bool = False
    # Consecutive failed refreshes and when to try again (ISO timestamp):
    # a conversation whose summary is always blocked must not retry every turn
    failures: int = 0
    retry_after: str | None = None

    @property
    def covered_count(self) -> int:
        """Leading history messages the summary replaces."""
        return self.segments[-1].end if self.segments else 0

    @property
    def summary(self) -> str | None:
        return render_segments(list(self.segments)) if self.segments else None


@dataclass(frozen=True)
class CompactionStatus:
    """What the next turn sends the model in place of the older history."""

    summarized_count: int
    total_count: int
    generation: int
    generation_estimated: bool
    summary: str


def _now() -> datetime:
    """Current UTC time (seam for tests - patching time.time also shifts date.today)."""
    return datetime.now(UTC)


def _estimate_generation(covered_count: int) -> int:
    """Infer summarization passes for legacy state that has no counter.

    The first pass covers at least ``THRESHOLD + 1 - KEEP_RECENT`` messages and
    each later pass at least ``RESUMMARIZE_BATCH`` more, so this is an upper
    bound on how many passes produced ``covered_count``.
    """
    first_pass = max(
        1,
        Config.CONVERSATION_COMPACTION_THRESHOLD + 1 - Config.CONVERSATION_COMPACTION_KEEP_RECENT,
    )
    batch = max(1, Config.CONVERSATION_COMPACTION_RESUMMARIZE_BATCH)
    return 1 + max(0, covered_count - first_pass) // batch


def _parse_state(data: dict[str, Any]) -> _State:
    failures = int(data.get("failures", 0))
    retry_after = data.get("retry_after")
    if "segments" in data:
        segments = tuple(
            Segment(str(s["text"]), int(s["end"]), int(s["passes"])) for s in data["segments"]
        )
        # A legacy state whose rebuild failed is re-saved in segment form but
        # keeps its marker, so the rebuild is retried once backoff clears
        return _State(
            segments,
            legacy=bool(data.get("legacy", False)),
            generation_estimated=bool(data.get("generation_estimated", False)),
            failures=failures,
            retry_after=retry_after,
        )
    # Legacy {summary, covered_count[, generation]} - one opaque segment
    summary = data.get("summary")
    covered_count = int(data.get("covered_count", 0))
    if not summary or covered_count <= 0:
        return _State(failures=failures, retry_after=retry_after)
    if "generation" in data:
        passes = int(data["generation"])
        estimated = bool(data.get("generation_estimated", False))
    else:
        passes, estimated = _estimate_generation(covered_count), True
    return _State(
        (Segment(summary, covered_count, passes),),
        legacy=True,
        generation_estimated=estimated,
        failures=failures,
        retry_after=retry_after,
    )


def _load_state(user_id: str, conversation_id: str) -> _State:
    """Load the persisted summary state (empty when absent or malformed)."""
    raw = db.kv_get(user_id, KV_NAMESPACE, conversation_id)
    if not raw:
        return _State()
    try:
        return _parse_state(json.loads(raw))
    except (ValueError, TypeError, AttributeError, KeyError):
        logger.warning(
            "Discarding malformed compaction state",
            extra={"conversation_id": conversation_id},
        )
        return _State()


def _save_state(user_id: str, conversation_id: str, state: _State) -> None:
    """Persist the segments (plus failure backoff, when set)."""
    data: dict[str, Any] = {
        "segments": [{"text": s.text, "end": s.end, "passes": s.passes} for s in state.segments],
        "covered_count": state.covered_count,
    }
    if state.legacy:
        data["legacy"] = True
    if state.generation_estimated:
        data["generation_estimated"] = True
    if state.failures:
        data["failures"] = state.failures
        data["retry_after"] = state.retry_after
    db.kv_set(user_id, KV_NAMESPACE, conversation_id, json.dumps(data))


def _in_backoff(state: _State) -> bool:
    if not state.retry_after:
        return False
    try:
        return _now() < datetime.fromisoformat(state.retry_after)
    except ValueError:
        return False


def _with_failure(state: _State) -> _State:
    """State after one more failed refresh: exponential backoff, capped."""
    failures = state.failures + 1
    delay = min(_FAILURE_BACKOFF_MAX_SECONDS, _FAILURE_BACKOFF_BASE_SECONDS * 2 ** (failures - 1))
    retry_after = (_now() + timedelta(seconds=delay)).isoformat()
    return replace(state, failures=failures, retry_after=retry_after)


def _summary_message(summary: str) -> dict[str, Any]:
    """Build the synthetic summary message (no volatile metadata, cache-stable)."""
    return {
        "role": "user",
        "content": f"{SUMMARY_PREFIX}\n\n{summary}\n\n{SUMMARY_RECALL_HINT}",
        "metadata": {},
    }


def _spawn_refresh(work: Callable[[], None]) -> None:
    """Run the refresh work on a daemon thread (patchable for tests)."""
    threading.Thread(target=work, daemon=True, name="compaction-summary").start()


def _refresh_segments(state: _State, older: list[dict[str, Any]]) -> list[Segment] | None:
    """New segment list covering all of ``older`` (LLM calls; None on failure).

    Legacy and empty states are rebuilt from scratch out of full message text;
    otherwise only the not-yet-covered messages are summarized and appended.
    """
    if state.legacy or not state.segments:
        return extend_segments([], older, 0, len(older))
    start = min(state.covered_count, len(older))
    return extend_segments(list(state.segments), older, start, len(older))


def _schedule_summary_refresh(
    user_id: str,
    conversation_id: str,
    older: list[dict[str, Any]],
    prior: _State,
) -> None:
    """Refresh the segmented summary in the background.

    The summarizer is an LLM call - running it synchronously added seconds to
    the user's turn whenever the un-summarized middle crossed the batch size.
    The current turn proceeds with whatever summary state exists; the fresh
    summary lands in kv_store for subsequent turns.
    """
    # Project eagerly: the worker must not share the caller's history dicts
    projected = [{"role": m["role"], "content": m["content"]} for m in older]

    with _inflight_lock:
        if conversation_id in _inflight_refreshes:
            return
        _inflight_refreshes.add(conversation_id)

    def _work() -> None:
        try:
            segments = _refresh_segments(prior, projected)
            if segments:
                _save_state(user_id, conversation_id, _State(tuple(segments)))
                logger.info(
                    "Compaction summary refreshed in background",
                    extra={
                        "conversation_id": conversation_id,
                        "summarized_messages": segments[-1].end,
                        "segments": len(segments),
                        "summary_words": len(render_segments(segments).split()),
                        "rebuilt": prior.legacy or not prior.segments,
                    },
                )
            else:
                failed = _with_failure(prior)
                _save_state(user_id, conversation_id, failed)
                logger.warning(
                    "Background summarization returned nothing",
                    extra={
                        "conversation_id": conversation_id,
                        "failures": failed.failures,
                        "retry_after": failed.retry_after,
                    },
                )
        except Exception:
            logger.warning(
                "Background compaction refresh failed",
                extra={"conversation_id": conversation_id},
                exc_info=True,
            )
        finally:
            with _inflight_lock:
                _inflight_refreshes.discard(conversation_id)
            # Close thread-local DB connections so the pool doesn't leak them
            try:
                db._pool.close_thread_connection()
            except Exception:
                logger.debug("Closing thread-local db connection failed", exc_info=True)

    _spawn_refresh(_work)


def summarized_message_ids(user_id: str, conversation_id: str) -> set[str]:
    """Ids of the conversation's messages currently replaced by the summary.

    They are no longer verbatim in the prompt, so conversation search must be
    able to reach them (the rest of the conversation is already in context).
    """
    covered_count = _load_state(user_id, conversation_id).covered_count
    if covered_count <= 0:
        return set()
    return {m.id for m in db.get_messages(conversation_id)[:covered_count]}


def _keep_recent_count(history: list[dict[str, Any]]) -> int | None:
    """Size of the verbatim recent tail, or None when compaction does not apply.

    Compaction applies once the history exceeds the configured message-count
    OR estimated-token threshold and is longer than the verbatim tail.
    """
    if not Config.CONVERSATION_COMPACTION_ENABLED:
        return None
    over_count = len(history) > Config.CONVERSATION_COMPACTION_THRESHOLD
    token_threshold = Config.CONVERSATION_COMPACTION_TOKEN_THRESHOLD
    over_tokens = token_threshold > 0 and _estimate_tokens(history) > token_threshold
    if not (over_count or over_tokens):
        return None

    keep_recent = Config.CONVERSATION_COMPACTION_KEEP_RECENT
    # A few huge recent messages can exceed the token threshold all by
    # themselves - shrink the verbatim tail (down to a floor) so compaction
    # actually bounds what is sent, not just how many messages frame it.
    if token_threshold > 0:
        while (
            keep_recent > _MIN_KEEP_RECENT
            and _estimate_tokens(history[-keep_recent:]) > token_threshold
        ):
            keep_recent -= 1
    if len(history) <= keep_recent:
        return None
    return keep_recent


def get_compaction_status(
    user_id: str,
    conversation_id: str,
    history: list[dict[str, Any]],
) -> CompactionStatus | None:
    """Describe how the next turn will compact ``history``, for display.

    Mirrors ``build_compacted_history`` without side effects (never schedules
    a summary refresh). Returns None when the next turn sends the history
    verbatim.

    Args:
        user_id: Owner of the conversation
        conversation_id: Conversation identifier (kv key)
        history: Enriched history dicts for the whole conversation so far
    """
    keep_recent = _keep_recent_count(history)
    if keep_recent is None:
        return None
    state = _load_state(user_id, conversation_id)
    covered_count = max(0, min(state.covered_count, len(history) - keep_recent))
    if not state.summary or covered_count == 0:
        return None
    return CompactionStatus(
        summarized_count=covered_count,
        total_count=len(history),
        generation=max_passes(list(state.segments)),
        generation_estimated=state.generation_estimated,
        summary=state.summary,
    )


def build_compacted_history(
    user_id: str | None,
    conversation_id: str | None,
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compact long conversation history for sending to the LLM.

    Returns ``[summary_message] + uncovered_middle + recent`` when the history
    exceeds the configured message-count OR estimated-token threshold,
    otherwise returns it unchanged. The running summary is regenerated only
    when the un-summarized middle has grown by
    ``CONVERSATION_COMPACTION_RESUMMARIZE_BATCH`` messages (appending a new
    segment), when legacy state needs rebuilding, and never while a failure
    backoff is running.

    Args:
        user_id: Owner of the conversation (required for kv persistence)
        conversation_id: Conversation identifier (kv key)
        history: Enriched history dicts (``role``, ``content``, ``metadata``)

    Returns:
        Possibly-compacted enriched history. The input is never mutated.
    """
    if not user_id or not conversation_id:
        return history
    keep_recent = _keep_recent_count(history)
    if keep_recent is None:
        return history

    older = history[:-keep_recent]
    recent = history[-keep_recent:]

    state = _load_state(user_id, conversation_id)
    prior_summary = state.summary
    # Clamp coverage in case history shrank (e.g. messages deleted from the UI)
    covered_count = max(0, min(state.covered_count, len(older)))
    uncovered = older[covered_count:]

    needs_resummarize = (
        prior_summary is None
        or state.legacy
        or len(uncovered) >= Config.CONVERSATION_COMPACTION_RESUMMARIZE_BATCH
    ) and not _in_backoff(state)

    if needs_resummarize:
        # OFF the request path: the LLM summarizer used to run synchronously
        # here, adding seconds to the user's turn every time the middle
        # crossed the batch size. The refreshed summary serves LATER turns;
        # this turn uses whatever state already exists. Deferring also keeps
        # this turn's history prefix byte-identical to the previous one,
        # which Gemini's implicit caching rewards.
        _schedule_summary_refresh(user_id, conversation_id, older, state)

    if prior_summary is None:
        # No usable summary yet — safest to send the full history unchanged.
        return history

    return [_summary_message(prior_summary)] + uncovered + recent
