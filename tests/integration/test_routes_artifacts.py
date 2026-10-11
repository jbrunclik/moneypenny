"""Artifact API: versions and saved state, owner only."""

from typing import TYPE_CHECKING

import pytest
from flask.testing import FlaskClient

from src.config import Config

if TYPE_CHECKING:
    from src.db.models import Conversation, Database


@pytest.fixture
def artifact_id(test_database: Database, test_conversation: Conversation) -> str:
    art, _ = test_database.create_artifact(
        test_conversation.id, test_conversation.user_id, "Tips", "<p>1</p>"
    )
    test_database.add_artifact_version(art.id, "<p>2</p>")
    return art.id


def test_owner_gets_a_version_with_state(
    client: FlaskClient, auth_headers: dict[str, str], artifact_id: str, test_database: Database
) -> None:
    test_database.set_artifact_state(artifact_id, {"checked": [2]})

    response = client.get(f"/api/artifacts/{artifact_id}/versions/1", headers=auth_headers)

    assert response.status_code == 200
    assert response.get_json() == {
        "id": artifact_id,
        "version": 1,
        "title": "Tips",
        "html": "<p>1</p>",
        "state": {"checked": [2]},
    }


def test_unknown_version_and_other_users_get_404(
    client: FlaskClient,
    auth_headers: dict[str, str],
    artifact_id: str,
    test_database: Database,
) -> None:
    assert (
        client.get(f"/api/artifacts/{artifact_id}/versions/9", headers=auth_headers).status_code
        == 404
    )
    assert client.get("/api/artifacts/nope/versions/1", headers=auth_headers).status_code == 404

    other = test_database.get_or_create_user(email="other@example.com", name="Other")
    conv = test_database.create_conversation(user_id=other.id, title="theirs")
    foreign, _ = test_database.create_artifact(conv.id, other.id, "F", "x")
    assert (
        client.get(f"/api/artifacts/{foreign.id}/versions/1", headers=auth_headers).status_code
        == 404
    )
    put = client.put(f"/api/artifacts/{foreign.id}/state", headers=auth_headers, json={"state": {}})
    assert put.status_code == 404


def test_state_put_round_trips_and_clears(
    client: FlaskClient, auth_headers: dict[str, str], artifact_id: str
) -> None:
    url = f"/api/artifacts/{artifact_id}/state"
    assert client.put(url, headers=auth_headers, json={"state": {"done": [1]}}).status_code == 200
    got = client.get(f"/api/artifacts/{artifact_id}/versions/2", headers=auth_headers)
    assert got.get_json()["state"] == {"done": [1]}

    assert client.put(url, headers=auth_headers, json={"state": None}).status_code == 200
    got = client.get(f"/api/artifacts/{artifact_id}/versions/2", headers=auth_headers)
    assert got.get_json()["state"] is None


def test_state_over_the_limit_is_refused(
    client: FlaskClient,
    auth_headers: dict[str, str],
    artifact_id: str,
    test_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Config, "ARTIFACT_STATE_MAX_BYTES", 20)
    test_database.set_artifact_state(artifact_id, {"a": 1})

    response = client.put(
        f"/api/artifacts/{artifact_id}/state",
        headers=auth_headers,
        json={"state": {"text": "far too long for the limit"}},
    )

    assert response.status_code == 413
    assert test_database.get_artifact(artifact_id).state == {"a": 1}


def test_requires_auth(client: FlaskClient, artifact_id: str) -> None:
    assert client.get(f"/api/artifacts/{artifact_id}/versions/1").status_code == 401


def test_state_may_be_any_json_value(
    client: FlaskClient, auth_headers: dict[str, str], artifact_id: str
) -> None:
    # mp.state.set takes any JSON (an artifact may save a plain list)
    url = f"/api/artifacts/{artifact_id}/state"
    assert client.put(url, headers=auth_headers, json={"state": [0, 2]}).status_code == 200
    got = client.get(f"/api/artifacts/{artifact_id}/versions/2", headers=auth_headers)
    assert got.get_json()["state"] == [0, 2]
