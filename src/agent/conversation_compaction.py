"""Non-destructive compaction for regular (non-agent) conversations.

Long chats re-send their entire history to the LLM every turn, so cost grows
~O(n^2) over a conversation. This module bounds the history *sent to the model*
by replacing older turns with a running summary while keeping recent turns
verbatim.

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
from dataclasses import dataclass
from typing import Any

from src.agent.compaction import summarize_messages
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
    """Persisted running summary for one conversation."""

    summary: str | None = None
    # Leading history messages the summary replaces
    covered_count: int = 0
    # Summarization passes folded into the summary (each pass loses detail)
    generation: int = 0
    # True when generation was inferred for state saved before it was tracked
    generation_estimated: bool = False


@dataclass(frozen=True)
class CompactionStatus:
    """What the next turn sends the model in place of the older history."""

    summarized_count: int
    total_count: int
    generation: int
    generation_estimated: bool
    summary: str


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


def _load_state(user_id: str, conversation_id: str) -> _State:
    """Load the persisted running summary and how many leading messages it covers."""
    raw = db.kv_get(user_id, KV_NAMESPACE, conversation_id)
    if not raw:
        return _State()
    try:
        data = json.loads(raw)
        summary = data.get("summary")
        covered_count = int(data.get("covered_count", 0))
        if "generation" in data:
            generation = int(data["generation"])
            estimated = bool(data.get("generation_estimated", False))
        else:
            generation = _estimate_generation(covered_count) if summary else 0
            estimated = bool(summary)
        return _State(summary, covered_count, generation, estimated)
    except (ValueError, TypeError, AttributeError):
        logger.warning(
            "Discarding malformed compaction state",
            extra={"conversation_id": conversation_id},
        )
        return _State()


def _save_state(user_id: str, conversation_id: str, state: _State) -> None:
    """Persist the running summary, its coverage and its generation."""
    data: dict[str, Any] = {
        "summary": state.summary,
        "covered_count": state.covered_count,
        "generation": state.generation,
    }
    if state.generation_estimated:
        data["generation_estimated"] = True
    db.kv_set(user_id, KV_NAMESPACE, conversation_id, json.dumps(data))


def _summary_message(summary: str) -> dict[str, Any]:
    """Build the synthetic summary message (no volatile metadata, cache-stable)."""
    return {
        "role": "user",
        "content": f"{SUMMARY_PREFIX}\n\n{summary}",
        "metadata": {},
    }


def _spawn_refresh(work: Callable[[], None]) -> None:
    """Run the refresh work on a daemon thread (patchable for tests)."""
    threading.Thread(target=work, daemon=True, name="compaction-summary").start()


def _schedule_summary_refresh(
    user_id: str,
    conversation_id: str,
    uncovered: list[dict[str, Any]],
    prior: _State,
    covered_target: int,
) -> None:
    """Refresh the running summary in the background.

    The summarizer is an LLM call - running it synchronously added seconds to
    the user's turn whenever the un-summarized middle crossed the batch size.
    The current turn proceeds with whatever summary state exists; the fresh
    summary lands in kv_store for subsequent turns.
    """
    # Project eagerly: the worker must not share the caller's history dicts
    projected = [{"role": m["role"], "content": m["content"]} for m in uncovered]

    with _inflight_lock:
        if conversation_id in _inflight_refreshes:
            return
        _inflight_refreshes.add(conversation_id)

    def _work() -> None:
        try:
            summary = summarize_messages(projected, prior_summary=prior.summary)
            if summary:
                refreshed = _State(
                    summary,
                    covered_target,
                    prior.generation + 1,
                    prior.generation_estimated,
                )
                _save_state(user_id, conversation_id, refreshed)
                logger.info(
                    "Compaction summary refreshed in background",
                    extra={
                        "conversation_id": conversation_id,
                        "summarized_messages": covered_target,
                    },
                )
            else:
                logger.warning(
                    "Background summarization returned nothing",
                    extra={"conversation_id": conversation_id},
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
        generation=state.generation,
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
    ``CONVERSATION_COMPACTION_RESUMMARIZE_BATCH`` messages.

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

    needs_resummarize = prior_summary is None or (
        len(uncovered) >= Config.CONVERSATION_COMPACTION_RESUMMARIZE_BATCH
    )

    if needs_resummarize:
        # OFF the request path: the LLM summarizer used to run synchronously
        # here, adding seconds to the user's turn every time the middle
        # crossed the batch size. The refreshed summary serves LATER turns;
        # this turn uses whatever state already exists. Deferring also keeps
        # this turn's history prefix byte-identical to the previous one,
        # which Gemini's implicit caching rewards.
        _schedule_summary_refresh(user_id, conversation_id, uncovered, state, len(older))

    if prior_summary is None:
        # No usable summary yet — safest to send the full history unchanged.
        return history

    return [_summary_message(prior_summary)] + uncovered + recent
