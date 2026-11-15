"""Where a turn's time goes (Nov 15 2026 audit: nothing measured time to first
token or the model's share): the timings ride on usage_info["timing"] into
message_costs.turn_timing."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from src.agent import chat_node
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
