"""Deep-research offers: validation, extraction and superseding."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from src.agent.deep_research.offer import PlanError, extract_offer, validate_plan
from src.config import Config


def _call(**args: object) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": "propose_deep_research", "args": args, "id": "p1"}]
    )


def test_validate_plan_strips_and_enforces_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "DEEP_RESEARCH_MAX_SUB_QUESTIONS", 2)
    assert validate_plan([" a ", "", "b"], " ctx ") == (["a", "b"], "ctx")
    with pytest.raises(PlanError):
        validate_plan([], "ctx")
    with pytest.raises(PlanError):
        validate_plan(["a", "b", "c"], "ctx")
    with pytest.raises(PlanError):
        validate_plan(["x" * (Config.DEEP_RESEARCH_MAX_ITEM_CHARS + 1)], "ctx")


def test_extract_offer_reads_the_tool_call_and_adds_the_estimate() -> None:
    offer = extract_offer(
        [_call(question="Q", context="Praha", sub_questions=["a", "b"], run_now=True)]
    )
    assert offer is not None
    assert (
        offer["sub_questions"] == ["a", "b"]
        and offer["status"] == "offered"
        and offer["autostart"] is True
    )
    assert set(offer["estimate"]) == {"minutes", "cost_czk"} and "rates" in offer


def test_invalid_offer_is_ignored() -> None:
    assert extract_offer([_call(question="Q", context="", sub_questions=[])]) is None


def test_saving_a_new_offer_supersedes_the_open_one(
    test_database: Any, test_conversation: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.api.helpers import chat_save

    monkeypatch.setattr(chat_save, "db", test_database)
    monkeypatch.setattr(chat_save, "calculate_and_save_message_cost", MagicMock())
    monkeypatch.setattr(chat_save, "_resolve_title_update", MagicMock(return_value=None))
    offer_call = _call(question="Q", context="Praha", sub_questions=["a", "b"])
    args = ([], {}, test_conversation.id, test_conversation.user_id, "m", "q", "r", True)

    first = chat_save.save_message_to_db("answer 1", [offer_call], *args)
    second = chat_save.save_message_to_db("answer 2", [offer_call], *args)

    assert first is not None and second is not None
    stored = {m.id: m for m in test_database.get_messages(test_conversation.id)}
    assert stored[first.message_id].research["offer"]["status"] == "superseded"
    assert stored[second.message_id].research["offer"]["status"] == "offered"


def test_the_tool_is_bound_for_chat_not_for_agents_or_programs() -> None:
    from src.agent.tools import get_tools_for_request

    def names(tools: list[Any]) -> set[str]:
        return {t.name for t in tools}

    assert "propose_deep_research" in names(get_tools_for_request())
    assert "propose_deep_research" in names(get_tools_for_request(anonymous_mode=True))
    assert "propose_deep_research" not in names(get_tools_for_request(is_sports=True))
    assert "propose_deep_research" not in names(get_tools_for_request(is_agent=True))
    assert "propose_deep_research" not in names(get_tools_for_request(agent_tool_permissions=[]))
