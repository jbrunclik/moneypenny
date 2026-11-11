"""Settings' instructions Review: run it, accept or reject one suggestion
(instructions self-tuning, docs/superpowers/specs/2026-11-11-instructions-self-tuning-design.md)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from flask.testing import FlaskClient

from src.agent import instructions_review
from src.db.models.memory import MemoryWrite
from src.services import instructions_tuning as it
from src.utils.clock import local_today

if TYPE_CHECKING:
    from src.db.models import Database, User

BASE = "/api/users/me/instructions-review"
RULE = "Never use bullet points."
_APPEND = {"instructions": {"op": "append", "new": RULE}}


@pytest.fixture
def chat(test_database: Database, test_user: User) -> None:
    test_database.update_user_custom_instructions(test_user.id, "Answer in Czech.")
    conv = test_database.create_conversation(test_user.id, "Chat")
    test_database.add_message(conv.id, "user", "stop using bullet points please")


@pytest.fixture
def model_suggests(monkeypatch: pytest.MonkeyPatch) -> None:
    item = instructions_review.ReviewItem(
        kind="add_rule",
        new_passage=RULE,
        summary="No bullet points",
        evidence=[f"{local_today().isoformat()}: 'stop using bullet points please'"],
    )
    monkeypatch.setattr(
        instructions_review,
        "_invoke",
        lambda prompt: (
            instructions_review.ReviewOutput(suggestions=[item]),
            {"input_tokens": 10, "output_tokens": 5},
        ),
    )


def _body(change: object, summary: str = "No bullet points") -> dict[str, object]:
    return {"change": change, "summary": summary, "evidence": ["Memory: x"]}


@pytest.mark.usefixtures("chat", "model_suggests")
class TestInstructionsReview:
    def test_review_lists_suggestions(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(BASE, headers=auth_headers)

        assert resp.status_code == 200
        [suggestion] = resp.get_json()["suggestions"]
        assert suggestion["summary"] == "No bullet points"
        assert suggestion["changes"] == [{"field": "Instructions", "before": "", "after": RULE}]

    def test_apply_returns_and_stores_the_new_text(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        resp = client.post(f"{BASE}/apply", headers=auth_headers, json=_body(_APPEND))

        assert resp.status_code == 200
        assert resp.get_json()["custom_instructions"] == f"Answer in Czech.\n\n{RULE}"
        user = test_database.get_user_by_id(test_user.id)
        assert user is not None and user.custom_instructions == f"Answer in Czech.\n\n{RULE}"

    def test_reject_remembers_the_decline(
        self, client: FlaskClient, auth_headers: dict[str, str], test_user: User
    ) -> None:
        resp = client.post(f"{BASE}/reject", headers=auth_headers, json=_body(_APPEND))

        assert resp.status_code == 204
        [entry] = it.declined(test_user.id)
        assert entry["fingerprint"] == it.fingerprint(_APPEND)  # type: ignore[arg-type]

    def test_a_malformed_change_is_a_validation_error(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        bad = {"instructions": {"op": "rewrite"}}
        resp = client.post(f"{BASE}/apply", headers=auth_headers, json=_body(bad))

        assert resp.status_code == 400

    def test_needs_auth(self, client: FlaskClient) -> None:
        assert client.post(BASE).status_code == 401


@pytest.mark.usefixtures("chat")
class TestCollisions:
    def test_a_changed_memory_comes_back_refreshed(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        memory = test_database.add_memory(test_user.id, "Prefers no bullet points", "preference")
        move = {**_APPEND, "memory": {"op": "delete", "id": memory.id, "expected": memory.content}}
        test_database.apply_memory_batch(
            test_user.id,
            None,
            [MemoryWrite("patch", memory.id, "Prefers no lists", expected=memory.content)],
        )

        resp = client.post(f"{BASE}/apply", headers=auth_headers, json=_body(move, "Move it"))

        assert resp.status_code == 409
        refreshed = resp.get_json()["error"]["details"]["suggestion"]
        assert refreshed["change"]["memory"]["expected"] == "Prefers no lists"
        assert refreshed["summary"] == "Move it"
        # Nothing changed
        user = test_database.get_user_by_id(test_user.id)
        assert user is not None and user.custom_instructions == "Answer in Czech."
        retry = client.post(
            f"{BASE}/apply", headers=auth_headers, json=_body(refreshed["change"], "Move it")
        )
        assert retry.status_code == 200

    def test_a_passage_that_is_gone_no_longer_applies(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        gone = {"instructions": {"op": "remove", "old": "Use lists."}}
        resp = client.post(f"{BASE}/apply", headers=auth_headers, json=_body(gone))

        assert resp.status_code == 400
        assert (
            resp.get_json()["error"]["message"] == "That no longer applies - nothing was changed."
        )
