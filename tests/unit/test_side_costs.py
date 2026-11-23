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


class TestEmbeddingCost:
    """Embeddings were the last side call outside side_costs (Nov 23 2026).
    The Gemini API returns no usage for them, so tokens are estimated from
    the characters sent."""

    def test_an_embedding_records_estimated_tokens_at_the_embedding_price(
        self, database: Database
    ) -> None:
        from src.config import Config
        from src.constants import EMBEDDING_CHARS_PER_TOKEN

        database.record_embedding_cost("x" * 4000, user_id="u1")

        [row] = _rows(database)
        tokens = 4000 // EMBEDDING_CHARS_PER_TOKEN
        price = Config.MODEL_PRICING[Config.EMBEDDING_MODEL]["input"]
        assert row["feature"] == "embedding"
        assert row["model"] == Config.EMBEDDING_MODEL
        assert row["input_tokens"] == tokens
        assert row["output_tokens"] == 0
        assert row["cost_usd"] == pytest.approx(tokens * price / 1_000_000)
        assert row["user_id"] == "u1"

    def test_only_the_characters_actually_sent_count(self, database: Database) -> None:
        from src.constants import EMBEDDING_CHARS_PER_TOKEN
        from src.utils.embeddings import MAX_EMBED_CHARS

        database.record_embedding_cost("y" * (MAX_EMBED_CHARS * 3), user_id=None)

        [row] = _rows(database)
        assert row["input_tokens"] == MAX_EMBED_CHARS // EMBEDDING_CHARS_PER_TOKEN

    def test_a_failed_write_never_raises(self, database: Database) -> None:
        with patch.object(database, "add_side_cost", side_effect=RuntimeError("disk")):
            database.record_embedding_cost("text", user_id="u1")  # no exception

    def test_a_background_embed_records_its_cost(self, database: Database) -> None:
        import threading

        from src.db.models import embeddings as embeddings_module

        done = threading.Event()
        with (
            patch.object(embeddings_module, "embed_text", return_value=[0.1, 0.2]),
            patch.object(embeddings_module.Config, "EMBEDDINGS_ENABLED", True),
            patch.object(database, "upsert_embedding", side_effect=lambda *a, **k: done.set()),
        ):
            database.embed_and_store_async("u1", "message", "m1", "hello there")
            assert done.wait(5)
        assert [r["feature"] for r in _rows(database)] == ["embedding"]
