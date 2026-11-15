"""Side calls (titles, reviews, AI assist, compaction, memory review and
summaries) record their spend: none of it reached message_costs (Nov 15 2026
audit; docs/superpowers/specs/2026-11-15-cost-telemetry-design.md)."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.db.models import use_database
from src.services import side_costs
from src.services.costs import calculate_token_cost
from src.services.side_costs import record_side_cost

if TYPE_CHECKING:
    from src.db.models import Database


@pytest.fixture
def database(test_database: Database) -> Iterator[Database]:
    with use_database(test_database):
        yield test_database


def _rows(db: Database) -> list[dict[str, object]]:
    with db._pool.get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM side_costs").fetchall()]


def test_a_langchain_reply_records_its_tokens_and_cost(database: Database) -> None:
    reply = AIMessage(
        content="ok",
        usage_metadata={
            "input_tokens": 1000,
            "output_tokens": 50,
            "total_tokens": 1050,
            "input_token_details": {"cache_read": 200},
        },
    )
    record_side_cost("title", "gemini-3.5-flash-lite", reply, user_id="u1")

    [row] = _rows(database)
    assert (row["feature"], row["model"], row["user_id"]) == (
        "title",
        "gemini-3.5-flash-lite",
        "u1",
    )
    assert (row["input_tokens"], row["cached_input_tokens"], row["output_tokens"]) == (
        1000,
        200,
        50,
    )
    assert row["cost_usd"] == pytest.approx(
        calculate_token_cost("gemini-3.5-flash-lite", 1000, 50, 200)
    )


def test_a_genai_response_records_its_tokens(database: Database) -> None:
    response = SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=800,
            cached_content_token_count=None,
            candidates_token_count=30,
            thoughts_token_count=20,
        )
    )
    record_side_cost("compaction", "gemini-4-hydrogen", response)

    [row] = _rows(database)
    assert (row["input_tokens"], row["cached_input_tokens"], row["output_tokens"]) == (800, 0, 50)
    assert row["user_id"] is None


def test_no_usage_records_nothing(database: Database) -> None:
    with patch.object(side_costs.logger, "warning") as warning:
        record_side_cost("title", "gemini-3.5-flash-lite", AIMessage(content="ok"))
    assert _rows(database) == []
    warning.assert_called_once()


def test_a_failure_to_record_never_raises(database: Database) -> None:
    reply = AIMessage(
        content="ok", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
    )
    with patch.object(database, "add_side_cost", side_effect=RuntimeError("locked")):
        record_side_cost("title", "gemini-3.5-flash-lite", reply)  # no raise


def test_a_title_records_its_cost(database: Database) -> None:
    from src.agent import title as title_mod
    from src.config import Config

    reply = AIMessage(
        content="🚲 Servis kola",
        usage_metadata={"input_tokens": 300, "output_tokens": 8, "total_tokens": 308},
    )
    factory = MagicMock()
    factory.return_value.invoke.return_value = reply
    with patch.object(title_mod, "chat_model", factory):
        title_mod.generate_title("servis", "odpověď")

    [row] = _rows(database)
    assert (row["feature"], row["model"]) == ("title", Config.TITLE_GENERATION_MODEL)
