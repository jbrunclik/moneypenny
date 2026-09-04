"""Integration tests for program quick actions (sports namespace; language shares the factory)."""

import json
from typing import TYPE_CHECKING

from flask.testing import FlaskClient

from src.api.routes.program_quick_actions import QUICK_ACTION_DEFAULTS

if TYPE_CHECKING:
    from src.db.models import Database, User


def _seed(test_database: "Database", user_id: str, program: dict) -> None:
    test_database.kv_set(user_id, "sports", "programs", json.dumps([program]))


LEGACY_PROGRAM = {
    "id": "pushups",
    "name": "Push-ups",
    "emoji": "\U0001f4aa",
    "created_at": "2026-01-01T00:00:00",
}

ACTION = {
    "id": "hang",
    "emoji": "\U0001f9d7",
    "label": "Hang test",
    "body": "Log my dead hang.",
    "fields": ["Hang time (s)"],
}


class TestListIncludesQuickActions:
    def test_legacy_program_gets_defaults(
        self, client: FlaskClient, auth_headers: dict, test_database: "Database", test_user: "User"
    ) -> None:
        _seed(test_database, test_user.id, LEGACY_PROGRAM)
        resp = client.get("/api/sports/programs", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["programs"][0]["quick_actions"] == QUICK_ACTION_DEFAULTS["sports"]

    def test_stored_actions_are_returned(
        self, client: FlaskClient, auth_headers: dict, test_database: "Database", test_user: "User"
    ) -> None:
        _seed(test_database, test_user.id, {**LEGACY_PROGRAM, "quick_actions": [ACTION]})
        resp = client.get("/api/sports/programs", headers=auth_headers)
        assert resp.get_json()["programs"][0]["quick_actions"] == [ACTION]

    def test_language_namespace_has_its_own_defaults(
        self, client: FlaskClient, auth_headers: dict, test_database: "Database", test_user: "User"
    ) -> None:
        test_database.kv_set(test_user.id, "language", "programs", json.dumps([LEGACY_PROGRAM]))
        resp = client.get("/api/language/programs", headers=auth_headers)
        assert resp.get_json()["programs"][0]["quick_actions"] == QUICK_ACTION_DEFAULTS["language"]


class TestCreateSeedsDefaults:
    def test_create_returns_and_persists_defaults(
        self, client: FlaskClient, auth_headers: dict, test_database: "Database", test_user: "User"
    ) -> None:
        resp = client.post(
            "/api/sports/programs",
            headers=auth_headers,
            json={"name": "Rowing", "emoji": "\U0001f6a3"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["programs"][0]["quick_actions"] == QUICK_ACTION_DEFAULTS["sports"]
        stored = json.loads(test_database.kv_get(test_user.id, "sports", "programs"))
        assert stored[0]["quick_actions"] == QUICK_ACTION_DEFAULTS["sports"]


class TestUpdateQuickActions:
    def test_requires_auth(self, client: FlaskClient) -> None:
        resp = client.put("/api/sports/programs/pushups/quick-actions", json={"quick_actions": []})
        assert resp.status_code == 401

    def test_unknown_program_404(self, client: FlaskClient, auth_headers: dict) -> None:
        resp = client.put(
            "/api/sports/programs/nope/quick-actions",
            headers=auth_headers,
            json={"quick_actions": []},
        )
        assert resp.status_code == 404

    def test_put_replaces_list_and_returns_program(
        self, client: FlaskClient, auth_headers: dict, test_database: "Database", test_user: "User"
    ) -> None:
        _seed(test_database, test_user.id, LEGACY_PROGRAM)
        resp = client.put(
            "/api/sports/programs/pushups/quick-actions",
            headers=auth_headers,
            json={"quick_actions": [ACTION]},
        )
        assert resp.status_code == 200
        item = resp.get_json()["programs"][0]
        assert item["id"] == "pushups"
        assert item["quick_actions"] == [ACTION]
        assert item["has_conversation"] is False
        stored = json.loads(test_database.kv_get(test_user.id, "sports", "programs"))
        assert stored[0]["quick_actions"] == [ACTION]

    def test_put_empty_list_clears_defaults(
        self, client: FlaskClient, auth_headers: dict, test_database: "Database", test_user: "User"
    ) -> None:
        _seed(test_database, test_user.id, LEGACY_PROGRAM)
        client.put(
            "/api/sports/programs/pushups/quick-actions",
            headers=auth_headers,
            json={"quick_actions": []},
        )
        resp = client.get("/api/sports/programs", headers=auth_headers)
        assert resp.get_json()["programs"][0]["quick_actions"] == []

    def test_put_rejects_over_limits(
        self, client: FlaskClient, auth_headers: dict, test_database: "Database", test_user: "User"
    ) -> None:
        _seed(test_database, test_user.id, LEGACY_PROGRAM)
        too_many = [{**ACTION, "id": f"a{i}"} for i in range(13)]
        resp = client.put(
            "/api/sports/programs/pushups/quick-actions",
            headers=auth_headers,
            json={"quick_actions": too_many},
        )
        assert resp.status_code == 400
        resp = client.put(
            "/api/sports/programs/pushups/quick-actions",
            headers=auth_headers,
            json={"quick_actions": [{**ACTION, "body": "x" * 2001}]},
        )
        assert resp.status_code == 400

    def test_corrupt_stored_actions_are_dropped_on_read(
        self, client: FlaskClient, auth_headers: dict, test_database: "Database", test_user: "User"
    ) -> None:
        _seed(
            test_database,
            test_user.id,
            {**LEGACY_PROGRAM, "quick_actions": [ACTION, {"id": "bad"}]},
        )
        resp = client.get("/api/sports/programs", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["programs"][0]["quick_actions"] == [ACTION]
