"""Eval cases for the background memory review (memory_review: true)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from evals import run
from evals.run import _tools_used, load_cases, tool_calls_in
from src.agent.memory_review import ReviewResult

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, User


def test_memory_review_field_loads(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text(
        "id: c\ndescription: d\nuser: hi\nmemory_review: true\nexpect:\n  rubric: r\n"
    )
    assert load_cases(tmp_path)[0].memory_review is True


def test_memory_review_case_reports_applied_ops_as_manage_memory_call(
    monkeypatch: pytest.MonkeyPatch,
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    seen: list[Any] = []
    op = {"action": "add", "content": "Ema - ballet on Tuesdays", "category": "fact"}

    def fake_review(user_id: str, conversation_id: str, messages: list[Any]) -> ReviewResult:
        seen.extend(messages)
        return ReviewResult(applied=[op["content"]], ops=[op], input_tokens=500, output_tokens=20)

    monkeypatch.setattr("src.agent.memory_review.review_messages", fake_review)
    monkeypatch.setattr("src.db.models.db", test_database)
    case = run.EvalCase(
        id="c",
        description="d",
        user="Ema has ballet every Tuesday at 17:00 by the way.",
        history=[
            {"role": "user", "content": "Dinner ideas?"},
            {"role": "assistant", "content": "Risotto"},
        ],
        memory_review=True,
    )

    response, tool_results, usage, result_messages, _ = run._memory_review_turn(
        case, test_user, test_conversation.id, case.history
    )

    assert [m.content for m in seen] == [
        "Dinner ideas?",
        "Risotto",
        "Ema has ballet every Tuesday at 17:00 by the way.",
    ]
    assert _tools_used(result_messages) == {"manage_memory"}
    assert tool_calls_in(result_messages)[0]["args"] == {"operations": [op]}
    assert "Ema - ballet on Tuesdays" in response
    assert usage["input_tokens"] == 500
    assert tool_results == []


def test_memory_review_case_with_nothing_saved_calls_no_tool(
    monkeypatch: pytest.MonkeyPatch,
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    monkeypatch.setattr(
        "src.agent.memory_review.review_messages", lambda *a: ReviewResult(input_tokens=1)
    )
    monkeypatch.setattr("src.db.models.db", test_database)
    case = run.EvalCase(id="c", description="d", user="Book a table tonight.", memory_review=True)

    response, _, _, result_messages, _ = run._memory_review_turn(
        case, test_user, test_conversation.id, None
    )

    assert _tools_used(result_messages) == set()
    assert "nothing" in response.lower()


def test_memory_review_cases_each_get_a_fresh_user(
    test_database: Database, test_user: User
) -> None:
    """Cases run in parallel as one user: a review case would see the others'
    memories and their deleted ones ("removed by the user - do not re-add")."""
    review = run.EvalCase(id="r", description="d", user="u", memory_review=True)
    plain = run.EvalCase(id="p", description="d", user="u")

    first = run._case_user(review, test_user, test_database)
    second = run._case_user(review, test_user, test_database)

    assert first.id != test_user.id
    assert first.id != second.id
    assert run._case_user(plain, test_user, test_database) is test_user
