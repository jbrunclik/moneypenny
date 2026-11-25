"""Projects API: membership, owner-only actions, caps, moving chats."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from src.auth.jwt_auth import create_token
from src.config import Config
from src.db.models.memory import MemoryWrite

if TYPE_CHECKING:
    from flask.testing import FlaskClient

    from src.db.models import Database, Project, User


@pytest.fixture
def jana(test_database: Database) -> User:
    return test_database.get_or_create_user(email="other@example.com", name="Jana")


@pytest.fixture
def jana_headers(jana: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(jana)}"}


@pytest.fixture
def project(test_database: Database, test_user: User) -> Project:
    return test_database.create_project(test_user.id, "Home", "Metric units")


def _json(response: Any) -> Any:
    return response.get_json()


class TestProjectsCrud:
    def test_create_and_list(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        created = client.post("/api/projects", headers=auth_headers, json={"name": "  Bikes  "})
        assert created.status_code == 201
        assert _json(created)["name"] == "Bikes"
        assert _json(created)["is_owner"] is True

        listed = _json(client.get("/api/projects", headers=auth_headers))
        assert [p["name"] for p in listed["projects"]] == ["Bikes"]
        assert listed["limit"] == Config.PROJECTS_MAX_PER_USER

    def test_create_past_cap_is_409(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(Config, "PROJECTS_MAX_PER_USER", 1)
        client.post("/api/projects", headers=auth_headers, json={"name": "A"})
        response = client.post("/api/projects", headers=auth_headers, json={"name": "B"})
        assert response.status_code == 409

    @pytest.mark.parametrize(
        "body",
        [
            {"name": ""},
            {"name": "   "},
            {"name": "x" * 61},
            {"name": "ok", "instructions": "x" * 4001},
        ],
    )
    def test_create_validates_lengths(
        self, client: FlaskClient, auth_headers: dict[str, str], body: dict[str, str]
    ) -> None:
        response = client.post("/api/projects", headers=auth_headers, json=body)
        assert response.status_code in (400, 422)

    def test_detail_lists_memory_and_authors(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        project: Project,
    ) -> None:
        test_database.apply_memory_batch(
            test_user.id,
            None,
            [
                MemoryWrite(
                    action="add", content="Garage 3-phase", category="fact", project_id=project.id
                )
            ],
            project_id=project.id,
        )
        data = _json(client.get(f"/api/projects/{project.id}", headers=auth_headers))

        assert data["instructions"] == "Metric units"
        assert [m["content"] for m in data["memories"]] == ["Garage 3-phase"]
        assert data["memories"][0]["author_name"] == test_user.name
        assert data["documents"] == []

    def test_non_member_gets_404_everywhere(
        self, client: FlaskClient, jana_headers: dict[str, str], project: Project
    ) -> None:
        base = f"/api/projects/{project.id}"
        assert client.get(base, headers=jana_headers).status_code == 404
        assert (
            client.patch(base, headers=jana_headers, json={"instructions": "x"}).status_code == 404
        )
        assert client.delete(base, headers=jana_headers).status_code == 404
        assert client.get(f"{base}/conversations", headers=jana_headers).status_code == 404

    def test_member_edits_instructions_but_not_name(
        self,
        client: FlaskClient,
        jana_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        jana: User,
        project: Project,
    ) -> None:
        test_database.add_project_member(project.id, test_user.id, jana.id)
        base = f"/api/projects/{project.id}"

        ok = client.patch(base, headers=jana_headers, json={"instructions": "Formal Czech"})
        renamed = client.patch(base, headers=jana_headers, json={"name": "Mine"})
        deleted = client.delete(base, headers=jana_headers)

        assert ok.status_code == 200
        assert renamed.status_code == 403
        assert deleted.status_code == 403
        got = test_database.get_project(project.id, test_user.id)
        assert got is not None
        assert got.instructions == "Formal Czech"
        assert got.name == "Home"

    def test_owner_renames_deletes_and_restores(
        self, client: FlaskClient, auth_headers: dict[str, str], project: Project
    ) -> None:
        base = f"/api/projects/{project.id}"
        assert (
            _json(client.patch(base, headers=auth_headers, json={"name": "Byt"}))["name"] == "Byt"
        )
        assert client.delete(base, headers=auth_headers).status_code == 200
        deleted = _json(client.get("/api/projects/deleted", headers=auth_headers))
        assert [p["id"] for p in deleted["projects"]] == [project.id]
        assert client.post(f"{base}/restore", headers=auth_headers).status_code == 200
        assert client.get(base, headers=auth_headers).status_code == 200


class TestMembers:
    def test_share_leave_and_people(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        jana_headers: dict[str, str],
        jana: User,
        project: Project,
    ) -> None:
        people = _json(client.get("/api/projects/people", headers=auth_headers))["people"]
        assert {"id": jana.id, "name": "Jana"} in people

        shared = client.put(f"/api/projects/{project.id}/members/{jana.id}", headers=auth_headers)
        assert shared.status_code == 200
        assert _json(shared)["shared"] is True
        assert client.get(f"/api/projects/{project.id}", headers=jana_headers).status_code == 200

        left = client.delete(f"/api/projects/{project.id}/members/{jana.id}", headers=jana_headers)
        assert left.status_code == 200
        assert client.get(f"/api/projects/{project.id}", headers=jana_headers).status_code == 404

    def test_member_cannot_add_or_remove_others(
        self,
        client: FlaskClient,
        jana_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        jana: User,
        project: Project,
    ) -> None:
        kid = test_database.get_or_create_user(email="allowed@example.com", name="Kid")
        test_database.add_project_member(project.id, test_user.id, jana.id)
        base = f"/api/projects/{project.id}/members"
        assert client.put(f"{base}/{kid.id}", headers=jana_headers).status_code == 403
        assert client.delete(f"{base}/{test_user.id}", headers=jana_headers).status_code == 403

    def test_add_unknown_user_is_404(
        self, client: FlaskClient, auth_headers: dict[str, str], project: Project
    ) -> None:
        response = client.put(f"/api/projects/{project.id}/members/nobody", headers=auth_headers)
        assert response.status_code == 404


class TestMovingChats:
    def test_move_in_list_and_out(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        project: Project,
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Wallbox")
        moved = client.put(
            f"/api/conversations/{conv.id}/project",
            headers=auth_headers,
            json={"project_id": project.id},
        )
        assert moved.status_code == 200

        page = _json(client.get(f"/api/projects/{project.id}/conversations", headers=auth_headers))
        assert [c["id"] for c in page["conversations"]] == [conv.id]
        assert page["conversations"][0]["project_id"] == project.id

        out = client.put(
            f"/api/conversations/{conv.id}/project", headers=auth_headers, json={"project_id": None}
        )
        assert out.status_code == 200
        page = _json(client.get(f"/api/projects/{project.id}/conversations", headers=auth_headers))
        assert page["conversations"] == []

    def test_move_into_foreign_project_is_404(
        self,
        client: FlaskClient,
        jana_headers: dict[str, str],
        test_database: Database,
        jana: User,
        project: Project,
    ) -> None:
        conv = test_database.create_conversation(jana.id, "Mine")
        response = client.put(
            f"/api/conversations/{conv.id}/project",
            headers=jana_headers,
            json={"project_id": project.id},
        )
        assert response.status_code == 404

    def test_bulk_move_ids(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        project: Project,
    ) -> None:
        a = test_database.create_conversation(test_user.id, "A")
        b = test_database.create_conversation(test_user.id, "B")
        response = client.post(
            "/api/conversations/bulk-move",
            headers=auth_headers,
            json={"ids": [a.id, b.id], "project_id": project.id},
        )
        assert sorted(_json(response)["moved_ids"]) == sorted([a.id, b.id])

    def test_bulk_move_all_except(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        project: Project,
    ) -> None:
        keep = test_database.create_conversation(test_user.id, "Keep")
        move = test_database.create_conversation(test_user.id, "Move")
        pinned = test_database.create_conversation(test_user.id, "Pinned")
        test_database.set_conversation_pinned(pinned.id, test_user.id, True)
        response = client.post(
            "/api/conversations/bulk-move",
            headers=auth_headers,
            json={
                "all": True,
                "exclude_ids": [keep.id],
                "created_before": "2099-01-01T00:00:00Z",
                "project_id": project.id,
            },
        )
        assert _json(response)["moved_ids"] == [move.id]


class TestShareNotification:
    def test_added_member_gets_a_push_once(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        jana: User,
        project: Project,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.api.routes.projects as routes

        sent: list[dict[str, Any]] = []
        monkeypatch.setattr(
            routes,
            "send_push_to_user",
            lambda user_id, **kw: sent.append({"user_id": user_id, **kw}),
        )
        url = f"/api/projects/{project.id}/members/{jana.id}"

        assert client.put(url, headers=auth_headers).status_code == 200
        assert client.put(url, headers=auth_headers).status_code == 200  # already a member

        assert len(sent) == 1
        assert sent[0]["user_id"] == jana.id
        assert sent[0]["url"] == f"/#/projects/{project.id}"
        assert "Home" in sent[0]["title"]
