"""/test/* control endpoints: reset, seeding, error simulation, mock turn behavior."""

import time
from typing import Any

from flask import Blueprint, g

from tests.e2e_server.context import DEFAULT_CONFIG, MOCK_CONFIG, isolated_configs

test_bp = Blueprint("test", __name__)


@test_bp.route("/test/reset", methods=["POST"])
def reset_database() -> tuple[dict[str, str], int]:
    """Reset database, blob store, and mock config to clean state for test isolation."""
    from flask import request

    # Reset main database (g.db is already the correct tenant DB)
    with g.db._pool.get_connection() as conn:
        # Delete all data but keep tables
        conn.execute("DELETE FROM message_costs")
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM conversations")
        conn.execute("DELETE FROM user_memories")
        conn.execute("DELETE FROM users")
        conn.commit()

    # Reset blob store
    with g.blob_store._pool.get_connection() as conn:
        conn.execute("DELETE FROM blobs")
        conn.commit()

    # Reset mock config to defaults for this test context
    test_id = request.headers.get("X-Test-Execution-Id", "default-shared-session")
    isolated_configs[test_id] = DEFAULT_CONFIG.copy()

    return {"status": "reset"}, 200


@test_bp.route("/test/seed", methods=["POST"])
def seed_data() -> tuple[dict[str, Any], int]:
    """Seed test data directly into database."""
    from flask import request

    data = request.get_json() or {}
    conversations_data = data.get("conversations", [])
    created_ids = []

    # Get or create the same user that auth bypass uses
    user = g.db.get_or_create_user(
        email="local@localhost",
        name="Local User",
    )

    for conv_data in conversations_data:
        # Create conversation
        title = conv_data.get("title", "Test Conversation")
        conv = g.db.create_conversation(user.id, title=title)
        created_ids.append(conv.id)

        # Add messages
        messages = conv_data.get("messages", [])
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            files = msg.get("files")
            added = g.db.add_message(conv.id, role, content, files=files)
            # Optional per-turn cost row (message_costs): tool rounds,
            # e.g. a reply cut off by the tool-round cap, or spend
            # (cost_usd) for the spend warning and the admin page
            if msg.get("tool_rounds") or msg.get("cost_usd"):
                g.db.save_message_cost(
                    added.id,
                    conv.id,
                    user.id,
                    "e2e",
                    0,
                    0,
                    float(msg.get("cost_usd", 0.0)),
                    tool_rounds=int(msg.get("tool_rounds", 0)),
                )

        # Seeded history counts as already read (as a real device that
        # wrote it would have reported); "unread": true keeps it unread
        if not conv_data.get("unread"):
            g.db.mark_conversation_read(conv.id, user.id, len(messages))

        # Optional running-summary state, as conversation compaction
        # persists it ({summary, covered_count, generation})
        compaction = conv_data.get("compaction")
        if compaction:
            import json

            from src.agent.conversation_compaction import KV_NAMESPACE

            g.db.kv_set(user.id, KV_NAMESPACE, conv.id, json.dumps(compaction))

    return {"status": "seeded", "conversation_ids": created_ids}, 200


@test_bp.route("/test/dump-threads", methods=["GET"])
def dump_threads() -> tuple[str, int]:
    """Dump all thread stacks (debugging aid for stuck E2E streams)."""
    import sys as _sys
    import traceback as _tb

    out = []
    for tid, frame in _sys._current_frames().items():
        out.append(f"--- thread {tid} ---")
        out.extend(_tb.format_stack(frame))
    return "\n".join(out), 200


@test_bp.route("/test/simulate-error", methods=["POST"])
def simulate_error() -> tuple[dict[str, Any], int]:
    """Simulate an error for testing error UI."""
    from src.api.errors import server_error

    return server_error("Simulated server error for testing")


@test_bp.route("/test/simulate-timeout", methods=["POST"])
def simulate_timeout() -> tuple[dict[str, Any], int]:
    """Simulate a timeout for testing error UI."""
    time.sleep(10)  # Delay long enough to trigger frontend timeout
    return {"status": "ok"}, 200


@test_bp.route("/test/set-mock-response", methods=["POST"])
def set_mock_response() -> tuple[dict[str, str], int]:
    from flask import request

    data = request.get_json() or {}
    response = data.get("response")
    # Uses context-aware MOCK_CONFIG
    MOCK_CONFIG["custom_response"] = response
    return {"status": "set", "response": response or "(default)"}, 200


@test_bp.route("/test/clear-mock-response", methods=["POST"])
def clear_mock_response() -> tuple[dict[str, str], int]:
    MOCK_CONFIG["custom_response"] = None
    return {"status": "cleared"}, 200


@test_bp.route("/test/set-stream-delay", methods=["POST"])
def set_stream_delay() -> tuple[dict[str, Any], int]:
    from flask import request

    data = request.get_json() or {}
    # Support both delay_ms (int) and delay (float seconds)
    if "delay_ms" in data:
        delay_ms = float(data["delay_ms"])
    else:
        delay_ms = float(data.get("delay", 0.05)) * 1000
    # Uses context-aware MOCK_CONFIG
    MOCK_CONFIG["stream_delay_ms"] = delay_ms
    return {"status": "set", "delay_ms": delay_ms}, 200


@test_bp.route("/test/set-emit-thinking", methods=["POST"])
def set_emit_thinking() -> tuple[dict[str, Any], int]:
    from flask import request

    data = request.get_json() or {}
    emit = data.get("emit", True)
    MOCK_CONFIG["emit_thinking"] = emit
    MOCK_CONFIG["thinking_text"] = data.get("text", "Let me think about this...")
    MOCK_CONFIG["thinking_hold_ms"] = int(data.get("hold_ms", 0))
    MOCK_CONFIG["thinking_until_released"] = bool(data.get("until_released", False))
    MOCK_CONFIG["thinking_released"] = False
    return {"status": "set", "emit_thinking": emit}, 200


@test_bp.route("/test/release-thinking", methods=["POST"])
def release_thinking() -> tuple[dict[str, Any], int]:
    # The held stream thread reads this same per-test config dict
    MOCK_CONFIG["thinking_released"] = True
    return {"status": "released"}, 200


@test_bp.route("/test/set-emit-retry", methods=["POST"])
def set_emit_retry() -> tuple[dict[str, Any], int]:
    from flask import request

    data = request.get_json() or {}
    hold_ms = int(data.get("hold_ms", 0))
    MOCK_CONFIG["emit_retry_hold_ms"] = hold_ms
    return {"status": "set", "emit_retry_hold_ms": hold_ms}, 200


@test_bp.route("/test/fail-next-stream", methods=["POST"])
def fail_next_stream() -> tuple[dict[str, Any], int]:
    MOCK_CONFIG["fail_next_stream"] = True
    return {"status": "set"}, 200


@test_bp.route("/test/set-consume-steering", methods=["POST"])
def set_consume_steering() -> tuple[dict[str, Any], int]:
    from flask import request

    MOCK_CONFIG["consume_steering"] = bool((request.get_json() or {}).get("consume", True))
    return {"status": "set"}, 200


@test_bp.route("/test/set-batch-delay", methods=["POST"])
def set_batch_delay() -> tuple[dict[str, Any], int]:
    from flask import request

    data = request.get_json() or {}
    # Support both delay_ms (int) and delay (float seconds)
    if "delay_ms" in data:
        delay_ms = float(data["delay_ms"])
    else:
        delay_ms = float(data.get("delay", 0.05)) * 1000
    MOCK_CONFIG["batch_delay_ms"] = delay_ms
    return {"status": "set", "delay_ms": delay_ms}, 200


@test_bp.route("/test/set-grounding-result", methods=["POST"])
def set_grounding_result() -> tuple[dict[str, Any], int]:
    """Make the (patched) grounding check return canned annotations."""
    from flask import request

    MOCK_CONFIG["grounding_result"] = request.get_json(silent=True) or None
    return {"status": "set"}, 200


@test_bp.route("/test/set-deep-research", methods=["POST"])
def set_deep_research() -> tuple[dict[str, Any], int]:
    """The next streamed turn proposes deep research with these offer args
    ({question, context, sub_questions, run_now?}); step_ms paces the fake run."""
    from flask import request

    data = request.get_json(silent=True) or {}
    MOCK_CONFIG["deep_research_offer"] = data.get("offer")
    if "step_ms" in data:
        MOCK_CONFIG["deep_research_step_ms"] = float(data["step_ms"])
    return {"status": "set"}, 200


@test_bp.route("/test/set-artifact", methods=["POST"])
def set_artifact() -> tuple[dict[str, Any], int]:
    """The next streamed turn makes an artifact through the real tool:
    {title, html} creates one, {html, update: true} adds a version."""
    from flask import request

    MOCK_CONFIG["artifact_next"] = request.get_json(silent=True) or None
    return {"status": "set"}, 200


@test_bp.route("/test/set-search-results", methods=["POST"])
def set_search_results() -> tuple[dict[str, Any], int]:
    """Set custom search results for testing search UI."""
    from flask import request

    data = request.get_json() or {}
    MOCK_CONFIG["search_results"] = data.get("results")
    MOCK_CONFIG["search_total"] = data.get("total", 0)
    return {"status": "set"}, 200


@test_bp.route("/test/clear-search-results", methods=["POST"])
def clear_search_results() -> tuple[dict[str, str], int]:
    """Clear custom search results to restore default behavior."""
    MOCK_CONFIG["search_results"] = None
    MOCK_CONFIG["search_total"] = 0
    return {"status": "cleared"}, 200
