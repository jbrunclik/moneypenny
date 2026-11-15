"""Where a turn's time goes (Nov 15 2026 audit: nothing measured time to first
token or the model's share): the timings ride on usage_info["timing"] into
message_costs.turn_timing."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from src.agent import cancellation, chat_node
from src.agent.retry import PartialStreamError
from src.agent.stream_events import StreamEventProcessor
from src.agent.turn_usage import MODEL_TIMING_KEY, ModelTiming, TurnClock, with_model_timing


def _config(timing: ModelTiming) -> dict[str, object]:
    return with_model_timing({"recursion_limit": 5}, timing)


def test_the_graph_config_keeps_its_settings() -> None:
    timing = ModelTiming()
    config = with_model_timing({"recursion_limit": 5, "configurable": {"a": 1}}, timing)
    assert config["recursion_limit"] == 5
    assert config["configurable"] == {"a": 1, MODEL_TIMING_KEY: timing}


def test_each_model_call_is_timed_with_its_finish_reason() -> None:
    model = MagicMock()
    model.invoke.return_value = AIMessage(content="ok", response_metadata={"finish_reason": "STOP"})
    timing = ModelTiming()
    chat_node._invoke_model(model, [], _config(timing))
    chat_node._invoke_model(model, [], _config(timing))
    assert timing.calls == 2
    assert timing.ms >= 0
    assert timing.finish_reason == "STOP"


def test_a_failed_model_call_still_counts() -> None:
    model = MagicMock()
    model.invoke.side_effect = ValueError("boom")
    timing = ModelTiming()
    with pytest.raises(ValueError):
        chat_node._invoke_model(model, [], _config(timing))
    assert timing.calls == 1


def test_a_call_without_a_clock_runs_as_before() -> None:
    model = MagicMock()
    model.invoke.return_value = AIMessage(content="ok")
    assert chat_node._invoke_model(model, [], None).content == "ok"


def test_the_stream_notes_when_the_first_text_went_out() -> None:
    processor = StreamEventProcessor([])
    assert processor.first_token_at is None
    list(processor.process("messages", (AIMessageChunk(content="Hi"), {})))
    first = processor.first_token_at
    assert first is not None
    list(processor.process("messages", (AIMessageChunk(content=" there"), {})))
    assert processor.first_token_at == first


def test_the_turns_timing() -> None:
    clock = TurnClock(started=100.0)
    clock.gate_ms = 900
    clock.lookup_ms = 2500
    clock.model.calls, clock.model.ms, clock.model.finish_reason = 2, 6400, "STOP"
    decision = SimpleNamespace(lookup=True, thinking="high")
    assert clock.timing(first_token_at=104.25, decision=decision) == {
        "first_token_ms": 4250,
        "gate_ms": 900,
        "lookup_ms": 2500,
        "model_ms": 6400,
        "model_calls": 2,
        "finish_reason": "STOP",
        "gate_lookup": True,
        "thinking": "high",
    }


def test_a_batch_turn_without_a_gate_leaves_out_what_it_did_not_measure() -> None:
    clock = TurnClock(started=0.0)
    clock.model.calls, clock.model.ms = 1, 7000
    assert clock.timing(first_token_at=None, decision=None) == {
        "model_ms": 7000,
        "model_calls": 1,
    }


def test_the_timing_is_stored_with_the_cost(test_database, test_conversation) -> None:
    test_database.save_message_cost(
        "m1",
        test_conversation.id,
        test_conversation.user_id,
        "gemini-x",
        10,
        5,
        0.01,
        turn_timing={"first_token_ms": 4250, "model_calls": 2},
    )
    with test_database._pool.get_connection() as conn:
        row = conn.execute(
            "SELECT json_extract(turn_timing, '$.first_token_ms') FROM message_costs"
            " WHERE message_id = 'm1'"
        ).fetchone()
    assert row[0] == 4250


def test_the_cost_service_passes_the_timing_on() -> None:
    from src.services import costs

    usage = {"input_tokens": 1, "output_tokens": 1, "timing": {"model_calls": 1}}
    with pytest.MonkeyPatch.context() as mp:
        save = MagicMock()
        mp.setattr(costs.db, "save_message_cost", save)
        costs.calculate_and_save_message_cost("m1", "c1", "u1", "gemini-2.5-flash", usage, [], 2)
    assert save.call_args.kwargs["turn_timing"] == {"model_calls": 1}
    assert json.dumps(save.call_args.kwargs["turn_timing"])


# The longest silence inside a model call: decides whether a stall watchdog
# is needed, and its threshold (docs/superpowers/specs/2026-11-15-title-speed-and-silence-design.md)


def _ticking(monkeypatch: pytest.MonkeyPatch, start: float = 0.0) -> list[float]:
    now = [start]
    monkeypatch.setattr(cancellation, "_clock", lambda: now[0])
    return now


def test_the_longest_gap_between_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    now = _ticking(monkeypatch)
    handler = cancellation.CancelOnToken()
    for at in (2.0, 3.0, 9.0):
        now[0] = at
        handler.on_llm_new_token("x", run_id=uuid4())
    now[0] = 10.0
    assert handler.longest_gap_s() == 6.0


def test_the_wait_for_the_first_chunk_and_after_the_last_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = _ticking(monkeypatch)
    handler = cancellation.CancelOnToken()
    now[0] = 7.0
    handler.on_llm_new_token("x", run_id=uuid4())
    now[0] = 8.0
    assert handler.longest_gap_s() == 7.0
    now[0] = 20.0
    assert handler.longest_gap_s() == 13.0


def test_thought_and_empty_chunks_are_not_silence(monkeypatch: pytest.MonkeyPatch) -> None:
    now = _ticking(monkeypatch)
    handler = cancellation.CancelOnToken()
    for at, token in ((1.0, [{"type": "thinking", "thinking": "hmm"}]), (2.0, ""), (3.0, "ok")):
        now[0] = at
        handler.on_llm_new_token(token, run_id=uuid4())
    assert handler.longest_gap_s() == 1.0


def test_a_call_with_no_chunks_has_no_silence(monkeypatch: pytest.MonkeyPatch) -> None:
    now = _ticking(monkeypatch)
    handler = cancellation.CancelOnToken()
    now[0] = 30.0
    assert handler.longest_gap_s() is None


def _streaming_model(
    now: list[float], chunks_at: list[float], end: float, fail: bool = False
) -> Any:
    def invoke(_messages: Any, config: Any) -> AIMessage:
        [handler] = [h for h in config["callbacks"] if isinstance(h, cancellation.CancelOnToken)]
        for at in chunks_at:
            now[0] = at
            handler.on_llm_new_token("x", run_id=uuid4())
        now[0] = end
        if fail:
            raise ValueError("boom")
        return AIMessage(content="ok")

    model = MagicMock()
    model.invoke.side_effect = invoke
    return model


def test_the_turn_keeps_its_longest_silence(monkeypatch: pytest.MonkeyPatch) -> None:
    now = _ticking(monkeypatch)
    timing = ModelTiming()
    chat_node._invoke_model(_streaming_model(now, [2.0, 3.0], 4.0), [], _config(timing))
    now[0] = 100.0
    chat_node._invoke_model(_streaming_model(now, [105.0], 106.0), [], _config(timing))
    assert timing.max_silence_ms == 5000


def test_a_failed_call_keeps_its_silence(monkeypatch: pytest.MonkeyPatch) -> None:
    now = _ticking(monkeypatch)
    timing = ModelTiming()
    with pytest.raises(PartialStreamError):  # text had streamed: not retried
        chat_node._invoke_model(_streaming_model(now, [1.0], 41.0, fail=True), [], _config(timing))
    assert timing.max_silence_ms == 40000


def test_a_batch_call_records_no_silence() -> None:
    model = MagicMock()
    model.invoke.return_value = AIMessage(content="ok")
    timing = ModelTiming()
    chat_node._invoke_model(model, [], _config(timing))
    assert timing.max_silence_ms is None
    clock = TurnClock(started=0.0)
    clock.model = timing
    assert "max_silence_ms" not in clock.timing(first_token_at=None, decision=None)


def test_the_silence_is_in_the_turns_timing() -> None:
    clock = TurnClock(started=0.0)
    clock.model.calls, clock.model.ms, clock.model.max_silence_ms = 1, 7000, 4200
    assert clock.timing(first_token_at=None, decision=None)["max_silence_ms"] == 4200


# Per-call cache use (docs/superpowers/specs/2026-11-15-cost-telemetry-design.md)


def test_each_call_records_its_tokens_and_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.messages import SystemMessage

    noted: list[tuple[str, str | None]] = []

    def note(key: str, user_id: str | None, _now: float) -> tuple[float | None, bool | None]:
        noted.append((key, user_id))
        return (42.0, False) if len(noted) > 1 else (None, None)

    monkeypatch.setattr(chat_node, "note_prefix_sent", note)
    model = MagicMock()
    model.model = "gemini-4-hydrogen"
    model.invoke.return_value = AIMessage(
        content="ok",
        usage_metadata={
            "input_tokens": 1000,
            "output_tokens": 20,
            "total_tokens": 1020,
            "input_token_details": {"cache_read": 600},
        },
    )
    timing = ModelTiming(user_id="user-a")
    messages = [SystemMessage(content="You are Moneypenny.")]
    chat_node._invoke_model(model, messages, _config(timing))
    chat_node._invoke_model(model, messages, _config(timing))

    first, second = timing.entries
    assert (first["input"], first["cached"], first["output"]) == (1000, 600, 20)
    assert first["prefix"] == second["prefix"] and len(str(first["prefix"])) == 8
    assert (first["gap_s"], first["same_user"]) == (None, None)
    assert (second["gap_s"], second["same_user"]) == (42.0, False)
    assert isinstance(first["ms"], int)
    assert noted[0][1] == "user-a"


def test_the_calls_are_in_the_turns_timing() -> None:
    clock = TurnClock(started=0.0)
    clock.model.calls, clock.model.ms = 1, 900
    clock.model.entries.append({"input": 10, "cached": 0, "output": 1, "ms": 900})
    assert clock.timing(first_token_at=None, decision=None)["calls"] == [
        {"input": 10, "cached": 0, "output": 1, "ms": 900}
    ]


def test_a_turn_without_calls_leaves_them_out() -> None:
    clock = TurnClock(started=0.0)
    assert "calls" not in clock.timing(first_token_at=None, decision=None)


def test_memory_fetches_are_in_the_turns_timing() -> None:
    """Condensed memories pay off while fewer than ~1 in 4 turns fetch one."""
    from src.agent.tool_results import set_current_request_id
    from src.agent.tools.turn_usage import record_tool_call

    set_current_request_id("req-fetches")
    try:
        record_tool_call("memory_fetch")
        record_tool_call("memory_fetch")
        timing = TurnClock(started=0.0).timing(first_token_at=None, decision=None)
    finally:
        set_current_request_id(None)
    assert timing["memory_fetches"] == 2
    assert "memory_fetches" not in TurnClock(started=0.0).timing(None, None)
