"""Device check runs and their fixture conversation (admin only).

The in-app runner measures the real layout on a device (the standalone PWA
on an iPhone, where no external automation reaches) and stores each run
here; the admin page lists them per build. The fixture conversation it
scrolls through is written straight to the database - no model call, no
embedding - archived so no list or sync shows it, and purged afterwards.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from flask.testing import FlaskClient

from src.config import Config
from src.db.models import Database, User

RUNS = "/api/admin/device-check-runs"
FIXTURE = "/api/admin/device-check-fixture"


@pytest.fixture
def as_admin(test_user: User) -> Iterator[None]:
    with patch.object(Config, "ADMIN_EMAILS", [test_user.email]):
        yield


def _scenario(scenario_id: str = "bottom", status: str = "passed", **extra: Any) -> dict[str, Any]:
    return {
        "id": scenario_id,
        "title": "Long conversation renders at the bottom",
        "status": status,
        "duration_ms": 812,
        "measurements": {"distance_from_bottom_px": 0.5, "window_scroll_y": 0, "standalone": True},
        "notes": [],
        **extra,
    }


def _run(**overrides: Any) -> dict[str, Any]:
    return {
        "build_marker": "kb19",
        "app_version": "abc1234",
        "standalone": True,
        "ua_summary": "iOS 26.1 · Safari 26.1",
        "environment": {"inner_height": 812, "safe_area_top": 62, "standalone": True},
        "scenarios": [
            _scenario(),
            _scenario("anchor", "failed", notes=["turn 9px below the anchor"]),
            _scenario("keyboard-open", "skipped", notes=["no software keyboard"]),
        ],
        "started_at": "2026-10-26T13:30:00.000Z",
        "finished_at": "2026-10-26T13:32:05.500Z",
        **overrides,
    }


class TestAccess:
    @pytest.mark.parametrize(
        ("method", "url"),
        [("get", RUNS), ("post", RUNS), ("post", FIXTURE), ("delete", FIXTURE)],
    )
    def test_requires_a_token(self, client: FlaskClient, method: str, url: str) -> None:
        assert getattr(client, method)(url, json={}).status_code == 401

    @pytest.mark.parametrize(
        ("method", "url", "body"),
        [
            ("get", RUNS, None),
            ("post", RUNS, _run()),
            ("post", FIXTURE, None),
            ("delete", FIXTURE, None),
        ],
    )
    def test_refuses_a_regular_user(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        method: str,
        url: str,
        body: dict[str, Any] | None,
    ) -> None:
        with patch.object(Config, "ADMIN_EMAILS", ["someone-else@example.com"]):
            response = getattr(client, method)(url, json=body, headers=auth_headers)
        assert response.status_code == 403


@pytest.mark.usefixtures("as_admin")
class TestRuns:
    def test_stores_a_run_and_counts_its_results(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(RUNS, json=_run(), headers=auth_headers)
        assert response.status_code == 201
        run = response.get_json()
        assert (run["passed"], run["failed"], run["skipped"]) == (1, 1, 1)
        assert run["build_marker"] == "kb19"
        assert run["standalone"] is True
        assert run["scenarios"][1]["notes"] == ["turn 9px below the anchor"]
        assert run["scenarios"][0]["measurements"]["standalone"] is True
        assert run["started_at"].startswith("2026-10-26T13:30:00")
        assert run["created_at"]

    def test_an_error_counts_as_failed(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        body = _run(scenarios=[_scenario(status="error", notes=["TypeError: x"])])
        run = client.post(RUNS, json=body, headers=auth_headers).get_json()
        assert (run["passed"], run["failed"], run["skipped"]) == (0, 1, 0)

    def test_history_is_newest_first(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        client.post(RUNS, json=_run(build_marker="kb18"), headers=auth_headers)
        client.post(RUNS, json=_run(build_marker="kb19"), headers=auth_headers)
        response = client.get(RUNS, headers=auth_headers)
        assert response.status_code == 200
        markers = [run["build_marker"] for run in response.get_json()["runs"]]
        assert markers == ["kb19", "kb18"]

    def test_history_honours_the_limit(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        for _ in range(3):
            client.post(RUNS, json=_run(), headers=auth_headers)
        runs = client.get(f"{RUNS}?limit=2", headers=auth_headers).get_json()["runs"]
        assert len(runs) == 2

    def test_keeps_only_the_newest_runs(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        with patch("src.db.models.device_checks.DEVICE_CHECK_RUNS_KEPT", 2):
            for marker in ("kb1", "kb2", "kb3"):
                client.post(RUNS, json=_run(build_marker=marker), headers=auth_headers)
        runs = client.get(RUNS, headers=auth_headers).get_json()["runs"]
        assert [run["build_marker"] for run in runs] == ["kb3", "kb2"]

    @pytest.mark.parametrize(
        "body",
        [
            {},
            _run(scenarios=[]),
            _run(scenarios=[_scenario(status="great")]),
            _run(started_at="yesterday"),
            _run(build_marker="x" * 100),
            _run(scenarios=[_scenario(measurements={"nested": {"a": 1}})]),
            _run(scenarios=[_scenario(measurements={f"m{i}": i for i in range(100)})]),
            _run(scenarios=[_scenario() for _ in range(60)]),
        ],
    )
    def test_rejects_an_invalid_run(
        self, client: FlaskClient, auth_headers: dict[str, str], body: dict[str, Any]
    ) -> None:
        assert client.post(RUNS, json=body, headers=auth_headers).status_code == 400


@pytest.mark.usefixtures("as_admin")
class TestFixture:
    def test_creates_an_archived_conversation_with_scripted_messages(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        response = client.post(FIXTURE, headers=auth_headers)
        assert response.status_code == 201
        body = response.get_json()
        assert body["message_count"] >= 60
        conversation = client.get(
            f"/api/conversations/{body['conversation_id']}", headers=auth_headers
        ).get_json()
        assert conversation["archived"] is True
        assert conversation["message_pagination"]["total_count"] == body["message_count"]
        roles = [m["role"] for m in conversation["messages"][-2:]]
        assert roles == ["user", "assistant"]
        # Not in the conversation list (other devices' sidebars and sync)
        listed = client.get("/api/conversations", headers=auth_headers).get_json()
        assert body["conversation_id"] not in {c["id"] for c in listed["conversations"]}

    def test_writes_no_embeddings(
        self, client: FlaskClient, auth_headers: dict[str, str], test_database: Database
    ) -> None:
        with (
            patch.object(Config, "EMBEDDINGS_ENABLED", True),
            patch.object(Database, "embed_and_store_async") as embed,
        ):
            assert client.post(FIXTURE, headers=auth_headers).status_code == 201
        embed.assert_not_called()

    def test_delete_purges_it_permanently(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        conv_id = client.post(FIXTURE, headers=auth_headers).get_json()["conversation_id"]
        assert client.delete(FIXTURE, headers=auth_headers).status_code == 204
        assert test_database.get_conversation(conv_id, test_user.id) is None
        assert test_database.get_messages(conv_id) == []
        # Not in the trash either
        trash = client.get("/api/conversations/trash", headers=auth_headers).get_json()
        assert trash["conversations"] == []

    def test_a_new_fixture_purges_one_a_crashed_run_left(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        stale = client.post(FIXTURE, headers=auth_headers).get_json()["conversation_id"]
        fresh = client.post(FIXTURE, headers=auth_headers).get_json()["conversation_id"]
        assert test_database.get_conversation(stale, test_user.id) is None
        assert test_database.get_conversation(fresh, test_user.id) is not None

    def test_never_touches_real_conversations(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        real = test_database.create_conversation(test_user.id, "Device check fixture")
        test_database.archive_conversation(real.id, test_user.id)
        client.post(FIXTURE, headers=auth_headers)
        client.delete(FIXTURE, headers=auth_headers)
        assert test_database.get_conversation(real.id, test_user.id) is not None

    def test_delete_without_a_fixture_is_fine(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        assert client.delete(FIXTURE, headers=auth_headers).status_code == 204
