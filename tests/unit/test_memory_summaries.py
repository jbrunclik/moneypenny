"""Condensed memories in the per-turn context: a short summary per long
memory, the full text a search_memory id lookup away
(docs/superpowers/specs/2026-11-15-cost-telemetry-design.md)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.agent import memory_summaries, scheduler
from src.agent.prompt_memory import get_user_memories_list_prompt
from src.agent.tool_results import set_current_request_id
from src.agent.tools.memory import search_memory
from src.agent.tools.turn_usage import get_tool_call_count
from src.config import Config
from src.db.models import use_database

if TYPE_CHECKING:
    from src.db.models import Database, User

_LONG = "Jiří rides a Canyon Endurace CF 7 with SRAM Rival AXS, " + "service notes " * 20


@pytest.fixture
def database(test_database: Database) -> Iterator[Database]:
    with use_database(test_database):
        yield test_database


def _add(db: Database, user: User, content: str) -> str:
    return db.add_memory(user.id, content, "fact").id


def _summary(db: Database, memory_id: str, user: User) -> str | None:
    memory = db.get_memory(memory_id, user.id)
    assert memory is not None
    return memory.summary


def _set_summary(db: Database, memory_id: str, summary: str) -> None:
    with db._pool.get_connection() as conn:
        [content] = conn.execute(
            "SELECT content FROM user_memories WHERE id = ?", (memory_id,)
        ).fetchone()
    assert db.set_memory_summary(memory_id, content, summary)


# ---- the column and the trigger ----


def test_long_unsummarised_memories_are_listed(database: Database, test_user: User) -> None:
    long_id = _add(database, test_user, _LONG)
    _add(database, test_user, "Short fact.")
    pending = database.memories_needing_summary(Config.MEMORY_SUMMARY_MAX_CHARS, 20)
    assert [m.id for m in pending] == [long_id]
    _set_summary(database, long_id, "Canyon Endurace CF 7, SRAM Rival AXS.")
    assert database.memories_needing_summary(Config.MEMORY_SUMMARY_MAX_CHARS, 20) == []


def test_changing_the_text_clears_the_summary(database: Database, test_user: User) -> None:
    """At the SQL level: every write path (tool, review, UI, defrag) is covered."""
    memory_id = _add(database, test_user, _LONG)
    _set_summary(database, memory_id, "A summary.")

    with database._pool.get_connection() as conn:
        conn.execute(
            "UPDATE user_memories SET content = ? WHERE id = ?", (_LONG + " Tubeless.", memory_id)
        )
        conn.commit()

    assert _summary(database, memory_id, test_user) is None


def test_the_bulk_update_clears_it_too(database: Database, test_user: User) -> None:
    memory_id = _add(database, test_user, _LONG)
    _set_summary(database, memory_id, "A summary.")
    database.bulk_update_memories(
        test_user.id, [], [(memory_id, _LONG + " Defragged.", "fact")], []
    )
    assert _summary(database, memory_id, test_user) is None


def test_protecting_keeps_the_summary(database: Database, test_user: User) -> None:
    memory_id = _add(database, test_user, _LONG)
    _set_summary(database, memory_id, "A summary.")
    database.set_memory_protected(memory_id, test_user.id, True)
    assert _summary(database, memory_id, test_user) == "A summary."


def test_a_summary_of_older_text_is_not_stored(database: Database, test_user: User) -> None:
    memory_id = _add(database, test_user, _LONG)
    assert not database.set_memory_summary(memory_id, "some older text", "Stale.")
    assert _summary(database, memory_id, test_user) is None


# ---- writing summaries ----


def _reply(text: str) -> AIMessage:
    return AIMessage(
        content=text, usage_metadata={"input_tokens": 200, "output_tokens": 30, "total_tokens": 230}
    )


def test_pending_memories_get_a_summary_and_its_cost(database: Database, test_user: User) -> None:
    memory_id = _add(database, test_user, _LONG)
    factory = MagicMock()
    factory.return_value.invoke.return_value = _reply("Canyon Endurace CF 7, SRAM Rival AXS. " * 10)
    with (
        patch.object(memory_summaries, "chat_model", factory),
        patch.object(memory_summaries, "record_side_cost") as cost,
    ):
        assert memory_summaries.summarize_pending() == 1

    summary = _summary(database, memory_id, test_user)
    assert summary is not None and summary.startswith("Canyon Endurace")
    assert len(summary) <= Config.MEMORY_SUMMARY_MAX_CHARS
    assert cost.call_args.args[:2] == ("memory_summary", Config.MEMORY_SUMMARY_MODEL)
    assert Config.MEMORY_SUMMARY_MODEL == "gemini-3.5-flash-lite"


def test_a_model_failure_writes_nothing(database: Database, test_user: User) -> None:
    memory_id = _add(database, test_user, _LONG)
    factory = MagicMock()
    factory.return_value.invoke.side_effect = RuntimeError("503")
    with patch.object(memory_summaries, "chat_model", factory):
        assert memory_summaries.summarize_pending() == 0
    assert _summary(database, memory_id, test_user) is None


def test_the_scheduler_pass_survives_a_summary_failure() -> None:
    with (
        patch.object(scheduler, "run_due_items") as items,
        patch.object(scheduler, "summarize_pending", side_effect=RuntimeError("down")),
        patch.object(scheduler, "purge_old_prefix_records"),
        patch.object(scheduler.db, "cleanup_zombie_executions", return_value=0),
        patch.object(scheduler, "expire_stale_run_cards"),
    ):
        items.return_value = MagicMock(fired=0, run=0, missed=0, expired=0)
        scheduler.run_scheduled_agents()  # no raise
        items.assert_called_once()


# ---- what the model sees ----


def test_the_list_shows_the_summary_of_a_long_memory(database: Database, test_user: User) -> None:
    long_id = _add(database, test_user, _LONG)
    _add(database, test_user, "Short fact.")
    _set_summary(database, long_id, "Canyon Endurace CF 7, SRAM Rival AXS.")

    listing = get_user_memories_list_prompt(test_user.id)
    entries = json.loads(listing.split("```json\n")[1].split("\n```")[0])
    by_content = {e["content"]: e for e in entries}
    assert by_content["Canyon Endurace CF 7, SRAM Rival AXS."]["full_chars"] == len(_LONG)
    assert "full_chars" not in by_content["Short fact."]
    assert _LONG not in listing


def test_an_unsummarised_long_memory_is_shown_whole(database: Database, test_user: User) -> None:
    _add(database, test_user, _LONG)
    assert _LONG in get_user_memories_list_prompt(test_user.id)


def test_search_by_id_returns_the_full_text_and_counts_a_fetch(
    database: Database, test_user: User
) -> None:
    memory_id = _add(database, test_user, _LONG)
    set_current_request_id("req-1")
    try:
        with patch(
            "src.agent.tools.memory.get_conversation_context", return_value=(None, test_user.id)
        ):
            result = search_memory.invoke({"query": memory_id})
        assert _LONG.strip() in result
        assert get_tool_call_count("memory_fetch") == 1
    finally:
        set_current_request_id(None)


def test_another_users_id_returns_nothing(database: Database, test_user: User) -> None:
    other = database.get_or_create_user("other@example.com", "Other")
    memory_id = _add(database, other, _LONG)
    with patch(
        "src.agent.tools.memory.get_conversation_context", return_value=(None, test_user.id)
    ):
        result = search_memory.invoke({"query": memory_id})
    assert _LONG not in result


# ---- final review fixes ----


def test_a_slow_model_cannot_stretch_the_pass(
    database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reminders run in the same oneshot pass: summaries get a time budget
    and stop at the first failure (final review)."""
    for i in range(5):
        _add(database, test_user, f"{i} " + _LONG)
    clock = [0.0]
    monkeypatch.setattr(memory_summaries, "_monotonic", lambda: clock[0])

    def slow(_messages: object) -> AIMessage:
        clock[0] += 12  # each call takes 12 s
        return _reply("Canyon Endurace CF 7.")

    factory = MagicMock()
    factory.return_value.invoke.side_effect = slow
    with (
        patch.object(memory_summaries, "chat_model", factory),
        patch.object(memory_summaries, "record_side_cost"),
    ):
        written = memory_summaries.summarize_pending()

    assert written == 2  # 0 s and 12 s started within the 20 s budget; 24 s did not
    assert Config.MEMORY_SUMMARIES_PASS_BUDGET_SECONDS == 20


def test_a_failure_ends_the_batch(database: Database, test_user: User) -> None:
    for i in range(3):
        _add(database, test_user, f"{i} " + _LONG)
    factory = MagicMock()
    factory.return_value.invoke.side_effect = TimeoutError("read timed out")
    with patch.object(memory_summaries, "chat_model", factory):
        memory_summaries.summarize_pending()
    assert factory.return_value.invoke.call_count == 1


def test_an_empty_reply_is_not_retried_every_pass(database: Database, test_user: User) -> None:
    """A blocked or empty reply would otherwise cost a call a minute, for ever."""
    memory_id = _add(database, test_user, _LONG)
    factory = MagicMock()
    factory.return_value.invoke.return_value = _reply("")
    with (
        patch.object(memory_summaries, "chat_model", factory),
        patch.object(memory_summaries, "record_side_cost"),
    ):
        memory_summaries.summarize_pending()
        memory_summaries.summarize_pending()
    assert factory.return_value.invoke.call_count == 1
    assert _LONG in get_user_memories_list_prompt(test_user.id)  # shown whole
    listing = get_user_memories_list_prompt(test_user.id)
    assert "full_chars" not in listing
    assert memory_id in listing


@pytest.mark.parametrize("form", ["id={}", "'{}'", '"{}"', " {} "])
def test_a_quoted_or_prefixed_id_still_finds_the_memory(
    database: Database, test_user: User, form: str
) -> None:
    memory_id = _add(database, test_user, _LONG)
    with patch(
        "src.agent.tools.memory.get_conversation_context", return_value=(None, test_user.id)
    ):
        result = search_memory.invoke({"query": form.format(memory_id)})
    assert _LONG.strip() in result


def test_the_guidance_covers_merging_and_deleting() -> None:
    """Consolidating from summaries alone would lose the details (final review)."""
    from src.agent.prompt_texts.memory import MEMORY_SYSTEM_PROMPT

    assert "patch, merge or delete a condensed entry" in " ".join(MEMORY_SYSTEM_PROMPT.split())
