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


def _load_state(user_id: str, conversation_id: str) -> tuple[str | None, int]:
    """Load the persisted running summary and how many leading messages it covers."""
    raw = db.kv_get(user_id, KV_NAMESPACE, conversation_id)
    if not raw:
        return None, 0
    try:
        data = json.loads(raw)
        return data.get("summary"), int(data.get("covered_count", 0))
    except (ValueError, TypeError):
        logger.warning(
            "Discarding malformed compaction state",
            extra={"conversation_id": conversation_id},
        )
        return None, 0


def _save_state(user_id: str, conversation_id: str, summary: str, covered_count: int) -> None:
    """Persist the running summary and its coverage."""
    db.kv_set(
        user_id,
        KV_NAMESPACE,
        conversation_id,
        json.dumps({"summary": summary, "covered_count": covered_count}),
    )


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
    prior_summary: str | None,
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
            summary = summarize_messages(projected, prior_summary=prior_summary)
            if summary:
                _save_state(user_id, conversation_id, summary, covered_target)
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


def build_compacted_history(
    user_id: str | None,
    conversation_id: str | None,
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compact long conversation history for sending to the LLM.

    Returns ``[summary_message] + uncovered_middle + recent`` when the history
    exceeds the configured threshold, otherwise returns it unchanged. The
    running summary is regenerated only when the un-summarized middle has grown
    by ``CONVERSATION_COMPACTION_RESUMMARIZE_BATCH`` messages.

    Args:
        user_id: Owner of the conversation (required for kv persistence)
        conversation_id: Conversation identifier (kv key)
        history: Enriched history dicts (``role``, ``content``, ``metadata``)

    Returns:
        Possibly-compacted enriched history. The input is never mutated.
    """
    if not Config.CONVERSATION_COMPACTION_ENABLED:
        return history
    if not user_id or not conversation_id:
        return history
    if len(history) <= Config.CONVERSATION_COMPACTION_THRESHOLD:
        return history

    keep_recent = Config.CONVERSATION_COMPACTION_KEEP_RECENT
    older = history[:-keep_recent]
    recent = history[-keep_recent:]

    prior_summary, covered_count = _load_state(user_id, conversation_id)
    # Clamp coverage in case history shrank (e.g. messages deleted from the UI)
    covered_count = max(0, min(covered_count, len(older)))
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
        _schedule_summary_refresh(user_id, conversation_id, uncovered, prior_summary, len(older))

    if prior_summary is None:
        # No usable summary yet — safest to send the full history unchanged.
        return history

    return [_summary_message(prior_summary)] + uncovered + recent
