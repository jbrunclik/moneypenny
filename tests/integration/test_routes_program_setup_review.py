"""The Quick actions sheet's setup Review: run it, accept or reject one suggestion
(program self-tuning, docs/superpowers/specs/2026-11-11-program-self-tuning-design.md)."""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING, Any

import pytest
from flask.testing import FlaskClient

from src.agent import program_review
from src.services import program_setup as ps
from src.services.program_setup import ProgramRef

if TYPE_CHECKING:
    from src.db.models import Database, User

BASE = "/api/sports/programs/cycling/setup-review"
_NEXT = {
    "id": "next",
    "emoji": "⏭️",
    "label": "Next workout",
    "body": "What is my next workout?",
    "fields": [],
}
_ADD = {
    "target": "quick_action",
    "op": "add",
    "action": {**_NEXT, "id": "plan-week", "label": "Plan week", "body": "Plan my week."},
}


@pytest.fixture
def program(test_database: Database, test_user: User) -> None:
    entry = {
        "id": "cycling",
        "name": "Cycling",
        "emoji": "🚴",
        "created_at": "2026-11-01",
        "quick_actions": [_NEXT],
    }
    test_database.kv_set(test_user.id, "sports", "programs", json.dumps([entry]))


@pytest.fixture
def model_suggests(monkeypatch: pytest.MonkeyPatch) -> None:
    item = program_review.ReviewItem(
        target="quick_action",
        op="add",
        emoji="📅",
        label="Plan week",
        body="Plan my week.",
        summary="Add a weekly plan",
        evidence=[f"{date.today().isoformat()}: 'plan my week'"],
    )
    monkeypatch.setattr(
        program_review,
        "_invoke",
        lambda prompt: (
            program_review.ReviewOutput(suggestions=[item]),
            {"input_tokens": 10, "output_tokens": 5},
        ),
    )


@pytest.mark.usefixtures("program", "model_suggests")
class TestSetupReview:
    def test_review_lists_suggestions(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(BASE, headers=auth_headers)
        assert resp.status_code == 200
        [suggestion] = resp.get_json()["suggestions"]
        assert suggestion["summary"] == "Add a weekly plan"
        assert suggestion["before"] == "(none)"
        assert "Plan week" in suggestion["after"]
        assert suggestion["change"]["target"] == "quick_action"

    def test_review_apply_and_reject_round_trip(
        self, client: FlaskClient, auth_headers: dict[str, str], test_user: User
    ) -> None:
        resp = client.post(
            f"{BASE}/apply", headers=auth_headers, json={"change": _ADD, "summary": "Add Plan week"}
        )
        assert resp.status_code == 200
        [item] = resp.get_json()["programs"]
        assert [a["label"] for a in item["quick_actions"]] == ["Next workout", "Plan week"]

        other: dict[str, Any] = {"target": "quick_action", "op": "remove", "action_id": "next"}
        resp = client.post(
            f"{BASE}/reject", headers=auth_headers, json={"change": other, "summary": "Remove Next"}
        )
        assert resp.status_code == 204
        [entry] = ps.declined(test_user.id, ProgramRef("sports", "cycling"))
        assert entry["summary"] == "Remove Next"

    def test_an_invalid_or_stale_change_is_a_400(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        bad = {"target": "instruction", "key": "progress", "patch": {"a": 1}}
        assert (
            client.post(
                f"{BASE}/apply", headers=auth_headers, json={"change": bad, "summary": "x"}
            ).status_code
            == 400
        )
        stale = {"target": "quick_action", "op": "remove", "action_id": "gone"}
        resp = client.post(
            f"{BASE}/apply", headers=auth_headers, json={"change": stale, "summary": "x"}
        )
        assert resp.status_code == 400
        assert "no longer" in resp.get_json()["error"]["message"]

    def test_another_users_program_is_a_404(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        assert (
            client.post(
                "/api/sports/programs/someone-else/setup-review", headers=auth_headers
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/language/programs/cycling/setup-review", headers=auth_headers
            ).status_code
            == 404
        )

    def test_requires_a_token(self, client: FlaskClient) -> None:
        assert client.post(BASE).status_code == 401

    def test_the_outcomes_are_logged(
        self, client: FlaskClient, auth_headers: dict[str, str], caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("INFO"):
            client.post(BASE, headers=auth_headers)
            client.post(
                f"{BASE}/apply",
                headers=auth_headers,
                json={"change": _ADD, "summary": "Add Plan week"},
            )
        assert any(r.getMessage() == "Setup review" for r in caplog.records)
        [resolved] = [r for r in caplog.records if r.getMessage() == "Setup suggestion resolved"]
        assert (resolved.source, resolved.outcome, resolved.target) == (
            "review",
            "approved",
            "quick_action",
        )  # type: ignore[attr-defined]
