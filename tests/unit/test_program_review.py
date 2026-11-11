"""The setup Review: one model call over the program's setup and recent turns,
its suggestions validated item by item (program self-tuning, Task 3)."""

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import date, timedelta
from typing import Any

import pytest

from src.agent import program_review as review
from src.db.models import Database, User, use_database
from src.enums import MessageRole
from src.services import program_setup as ps
from src.services.program_setup import ProgramRef

REF = ProgramRef("sports", "cycling")
_NEXT = {
    "id": "next",
    "emoji": "⏭️",
    "label": "Next workout",
    "body": "What is my next workout?",
    "fields": [],
}
TODAY = date.today().isoformat()


@pytest.fixture
def program(test_database: Database, test_user: User) -> Generator[Database]:
    with use_database(test_database):
        entry = {
            "id": "cycling",
            "name": "Cycling",
            "emoji": "🚴",
            "created_at": "2026-11-01",
            "quick_actions": [_NEXT],
        }
        test_database.kv_set(test_user.id, "sports", "programs", json.dumps([entry]))
        test_database.kv_set(
            test_user.id, "sports", "cycling:routine", json.dumps({"z2_watts": 120})
        )
        # The day the suggestions cite: the user wrote in the program chat today
        conv = test_database.get_or_create_program_conversation("sports", test_user.id, "cycling")
        test_database.add_message(conv.id, MessageRole.USER, "plan my week please")
        yield test_database


def _item(**over: Any) -> review.ReviewItem:
    base: dict[str, Any] = {
        "target": "quick_action",
        "op": "add",
        "emoji": "📅",
        "label": "Plan week",
        "body": "Plan my training week.",
        "fields": [],
        "summary": "Add a weekly plan action",
        "evidence": [f"{TODAY}: 'plan my week'"],
    }
    base.update(over)
    return review.ReviewItem(**base)


def _returns(
    monkeypatch: pytest.MonkeyPatch, items: list[review.ReviewItem], seen: list[str] | None = None
) -> None:
    def fake(prompt: str) -> tuple[review.ReviewOutput, dict[str, int]]:
        if seen is not None:
            seen.append(prompt)
        return review.ReviewOutput(suggestions=items), {"input_tokens": 1000, "output_tokens": 200}

    monkeypatch.setattr(review, "_invoke", fake)


def test_returns_validated_suggestions_with_before_after(
    program: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _returns(
        monkeypatch,
        [
            _item(),
            _item(
                target="instruction",
                key="routine",
                patch_json='{"z2_watts": 125}',
                summary="Raise Z2 to 125 W",
            ),
        ],
    )

    [add, routine] = review.review_setup(test_user.id, REF)

    assert add["before"] == "(none)" and "Plan week" in add["after"]
    assert add["id"] == ps.fingerprint(add["change"])
    change = dict(routine["change"])
    assert change.pop("expect")  # the snapshot of the routine as it is now
    assert change == {"target": "instruction", "key": "routine", "patch": {"z2_watts": 125}}
    assert "120" in routine["before"] and "125" in routine["after"]
    # The sheet shows only the changed field
    assert routine["changes"] == [{"field": "z2 watts", "before": "120", "after": "125"}]
    assert routine["evidence"] == [f"{TODAY}: 'plan my week'"]


def test_the_model_sees_setup_declines_and_dated_turns(
    program: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    conv = program.get_or_create_program_conversation("sports", test_user.id, "cycling")
    program.add_message(conv.id, MessageRole.USER, "what's my next workout?")
    ps.record_decline(
        test_user.id,
        REF,
        ps.validate_change(
            "sports", {"target": "quick_action", "op": "remove", "action_id": "next"}
        ),
        "Remove Next workout",
    )  # type: ignore[arg-type]
    seen: list[str] = []
    _returns(monkeypatch, [], seen)

    assert review.review_setup(test_user.id, REF) == []
    [prompt] = seen
    assert "Next workout" in prompt and "z2_watts" in prompt
    assert "Remove Next workout" in prompt
    assert f"{TODAY} user: what's my next workout?" in prompt


def test_invalid_and_declined_items_are_dropped(
    program: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    declined_change = ps.validate_change(
        "sports",
        {
            "target": "quick_action",
            "op": "add",
            "action": {**_NEXT, "id": "x", "label": "Old idea", "body": "Old idea."},
        },
    )
    ps.record_decline(test_user.id, REF, declined_change, "Add Old idea")  # type: ignore[arg-type]
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    _returns(
        monkeypatch,
        [
            _item(
                target="instruction", key="progress", patch_json='{"a": 1}'
            ),  # not an instruction key
            _item(fields=["a", "b", "c", "d", "e", "f", "g"]),  # too many fields
            _item(evidence=[]),  # no evidence
            _item(evidence=["often"]),  # undated
            _item(
                label="Old idea", body="Old idea.", evidence=[f"{yesterday}: x"]
            ),  # declined, older evidence
            _item(target="instruction", key="routine", patch_json="not json"),
            _item(label="Keeper"),
        ],
    )

    suggestions = review.review_setup(test_user.id, REF)

    assert [s["summary"] for s in suggestions] == ["Add a weekly plan action"]
    assert "Keeper" in suggestions[0]["after"]


def test_a_program_without_a_chat_has_nothing_to_cite(
    program: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    running = {"id": "running", "name": "Running", "emoji": "🏃", "created_at": "2026-11-01"}
    cycling = json.loads(program.kv_get(test_user.id, "sports", "programs") or "[]")
    program.kv_set(test_user.id, "sports", "programs", json.dumps([*cycling, running]))
    seen: list[str] = []
    _returns(monkeypatch, [_item()], seen)

    assert review.review_setup(test_user.id, ProgramRef("sports", "running")) == []
    assert "(no turns yet)" in seen[0]


def test_evidence_must_cite_days_the_user_wrote(
    program: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final review #4: a made-up date drops the suggestion."""
    made_up = (date.today() - timedelta(days=9)).isoformat()
    _returns(monkeypatch, [_item(evidence=[f"{made_up}: never said"]), _item(label="Real")])
    [kept] = review.review_setup(test_user.id, REF)
    assert "Real" in kept["after"]


def test_a_czech_label_still_makes_a_valid_add(
    program: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final review #3: the id built from "Plán týdne" was not ASCII and every Czech add vanished."""
    _returns(monkeypatch, [_item(label="Plán týdne", body="Naplánuj mi týden.")])
    [suggestion] = review.review_setup(test_user.id, REF)
    action = suggestion["change"]["action"]
    assert action["label"] == "Plán týdne"
    assert action["id"] == "plan-tydne"


def test_a_suggestion_carries_a_snapshot_of_its_target(
    program: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final review #1: accepting after a hand edit is refused, not applied over it."""
    edit = _item(op="edit", action_id="next", label="Next workout", body="Coach's version")
    _returns(monkeypatch, [edit])
    [suggestion] = review.review_setup(test_user.id, REF)
    assert suggestion["change"].get("expect")


def test_at_most_eight(program: Database, test_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    _returns(monkeypatch, [_item(label=f"Action {i}", summary=f"S{i}") for i in range(12)])
    assert len(review.review_setup(test_user.id, REF)) == 8


def test_the_review_logs_its_cost(
    program: Database,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _returns(monkeypatch, [_item()])
    with caplog.at_level("INFO"):
        review.review_setup(test_user.id, REF)
    [line] = [r for r in caplog.records if r.getMessage() == "Setup review"]
    assert line.suggestions == 1  # type: ignore[attr-defined]
    assert line.cost_usd > 0  # type: ignore[attr-defined]
    assert line.namespace == "sports"  # type: ignore[attr-defined]


def test_an_answer_that_cannot_be_read_is_an_error_not_nothing_to_change(
    program: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        review, "_invoke", lambda prompt: (None, {"input_tokens": 1, "output_tokens": 0})
    )

    with pytest.raises(review.ReviewUnreadableError):
        review.review_setup(test_user.id, REF)
