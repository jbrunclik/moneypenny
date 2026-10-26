"""A model-usage sink records every model call's tokens as it happens.

Deep-research subagents are cut mid-turn (deadline, Finish now, Stop); the
turn's own usage never comes back then, so spend is recorded per call.
"""

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from src.agent import graph
from src.agent.turn_usage import TokenTotals, collecting_model_usage, record_model_usage

USAGE = {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}


def test_calls_inside_the_block_are_recorded() -> None:
    totals = TokenTotals()
    with collecting_model_usage(totals):
        record_model_usage(AIMessage(content="a", usage_metadata=USAGE))
        record_model_usage(AIMessage(content="b", usage_metadata=USAGE))
    record_model_usage(AIMessage(content="c", usage_metadata=USAGE))  # outside: ignored

    assert (totals.input_tokens, totals.output_tokens) == (240, 60)


def test_without_a_sink_nothing_happens() -> None:
    record_model_usage(AIMessage(content="a", usage_metadata=USAGE))  # no error


def test_every_graph_model_call_feeds_the_sink() -> None:
    model = MagicMock()
    model.invoke.return_value = AIMessage(content="answer", usage_metadata=USAGE)
    totals = TokenTotals()

    with collecting_model_usage(totals):
        graph._invoke_model(model, [], None)

    assert totals.input_tokens == 120
