"""The standing chat editor on /api/jobs: CRUD, run now, runs (standing chats phase 3)."""

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Database, StandingChat, User


class TestCreateAgent:
    """Tests for POST /api/jobs endpoint."""

    def test_creates_agent(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should create new agent."""
        response = client.post(
            "/api/jobs",
            headers=auth_headers,
            json={"name": "New StandingChat"},
        )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert "id" in data
        assert data["name"] == "New StandingChat"
        assert data["timezone"] == "UTC"  # Default
        assert data["enabled"] is True  # Default

    def test_no_tools_selected_stays_restricted(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """An empty permission list means "only the safe tools"; it was stored
        as NULL - "no restrictions" - so the agent got every tool."""
        response = client.post(
            "/api/jobs", headers=auth_headers, json={"name": "Quiet", "grants": []}
        )

        assert response.status_code == 201
        agent = test_database.get_standing_chat(json.loads(response.data)["id"], test_user.id)
        assert agent is not None and agent.grants == []

    def test_creates_with_all_fields(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should create agent with all optional fields."""
        response = client.post(
            "/api/jobs",
            headers=auth_headers,
            json={
                "name": "Full StandingChat",
                "description": "A fully configured agent",
                "instructions": "You are helpful",
                "schedule": "0 9 * * 1-5",
                "timezone": "America/New_York",
                "grants": ["web_search", "todoist"],
                "enabled": False,
            },
        )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["name"] == "Full StandingChat"
        assert data["description"] == "A fully configured agent"
        assert data["schedule"] == "0 9 * * 1-5"
        assert data["timezone"] == "America/New_York"
        assert data["enabled"] is False

    def test_rejects_invalid_cron(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should return 400 for invalid cron expression."""
        response = client.post(
            "/api/jobs",
            headers=auth_headers,
            json={"name": "Bad Cron StandingChat", "schedule": "invalid cron"},
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_refuses_an_admin_only_model_for_the_family(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        from src.config import Config

        with patch.object(Config, "ADMIN_EMAILS", ["someone-else@example.com"]):
            response = client.post(
                "/api/jobs",
                headers=auth_headers,
                json={"name": "Deep Thinker", "model": "gemini-4-carbon"},
            )

        assert response.status_code == 400

    def test_rejects_invalid_timezone(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 400 for invalid timezone."""
        response = client.post(
            "/api/jobs",
            headers=auth_headers,
            json={"name": "Bad TZ StandingChat", "timezone": "Invalid/Timezone"},
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_rejects_duplicate_name(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: StandingChat,
    ) -> None:
        """Should return 400 for duplicate agent name."""
        response = client.post(
            "/api/jobs",
            headers=auth_headers,
            json={"name": "Test Agent"},  # Same name as test_agent
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "already exists" in data["error"]["message"]

    def test_rejects_empty_name(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should return 400 for empty name."""
        response = client.post(
            "/api/jobs",
            headers=auth_headers,
            json={"name": ""},
        )

        assert response.status_code == 400

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.post("/api/jobs", json={"name": "Test"})
        assert response.status_code == 401


class TestGetAgent:
    """Tests for GET /api/jobs/<agent_id> endpoint."""

    def test_gets_agent(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: StandingChat,
    ) -> None:
        """Should return agent details."""
        response = client.get(
            f"/api/jobs/{test_agent.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["id"] == test_agent.id
        assert data["name"] == "Test Agent"
        assert "unread_count" in data
        assert "has_pending_approval" in data

    def test_returns_404_for_nonexistent(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for non-existent agent."""
        response = client.get(
            "/api/jobs/nonexistent-id",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_returns_404_for_other_users_agent(
        self,
        client: FlaskClient,
        test_database: Database,
        test_agent: StandingChat,
    ) -> None:
        """Should return 404 when accessing another user's agent."""
        # Create another user
        other_user = test_database.get_or_create_user(email="other@example.com", name="Other")

        # Get a token for the other user
        from src.auth.jwt_auth import create_token

        other_token = create_token(other_user)

        response = client.get(
            f"/api/jobs/{test_agent.id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient, test_agent: StandingChat) -> None:
        """Should return 401 without authentication."""
        response = client.get(f"/api/jobs/{test_agent.id}")
        assert response.status_code == 401


class TestUpdateAgent:
    """Tests for PATCH /api/jobs/<agent_id> endpoint."""

    def test_updates_name(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: StandingChat,
    ) -> None:
        """Should update agent name."""
        response = client.patch(
            f"/api/jobs/{test_agent.id}",
            headers=auth_headers,
            json={"name": "Updated StandingChat Name"},
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["name"] == "Updated StandingChat Name"

    def test_update_refuses_an_admin_only_model_for_the_family(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: StandingChat,
    ) -> None:
        from src.config import Config

        with patch.object(Config, "ADMIN_EMAILS", ["someone-else@example.com"]):
            response = client.patch(
                f"/api/jobs/{test_agent.id}",
                headers=auth_headers,
                json={"model": "gemini-4-carbon"},
            )

        assert response.status_code == 400

    def test_updates_multiple_fields(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: StandingChat,
    ) -> None:
        """Should update multiple fields at once."""
        response = client.patch(
            f"/api/jobs/{test_agent.id}",
            headers=auth_headers,
            json={
                "description": "New description",
                "schedule": "0 10 * * *",
                "enabled": False,
            },
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["description"] == "New description"
        assert data["schedule"] == "0 10 * * *"
        assert data["enabled"] is False

    def test_clears_schedule(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: StandingChat,
    ) -> None:
        """Should clear schedule by setting to empty string."""
        response = client.patch(
            f"/api/jobs/{test_agent.id}",
            headers=auth_headers,
            json={"schedule": ""},
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["schedule"] == "" or data["schedule"] is None

    def test_clears_tool_permissions(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: StandingChat,
    ) -> None:
        """Should clear tool permissions by setting to empty list."""
        # First set some permissions
        client.patch(
            f"/api/jobs/{test_agent.id}",
            headers=auth_headers,
            json={"grants": ["web_search"]},
        )

        # Now clear them
        response = client.patch(
            f"/api/jobs/{test_agent.id}",
            headers=auth_headers,
            json={"grants": []},
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["grants"] == []

    def test_clears_budget_limit(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: StandingChat,
    ) -> None:
        """Should clear budget limit by setting to null."""
        # First set a limit
        client.patch(
            f"/api/jobs/{test_agent.id}",
            headers=auth_headers,
            json={"budget_usd": 10.0},
        )

        # Now clear it (set to null)
        response = client.patch(
            f"/api/jobs/{test_agent.id}",
            headers=auth_headers,
            json={"budget_usd": None},
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["budget_usd"] is None

    def test_partial_update_preserves_other_fields(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: StandingChat,
    ) -> None:
        """Should only update provided fields and preserve others."""
        # Set initial state
        client.patch(
            f"/api/jobs/{test_agent.id}",
            headers=auth_headers,
            json={
                "description": "Original description",
                "budget_usd": 50.0,
            },
        )

        # Update only name
        response = client.patch(
            f"/api/jobs/{test_agent.id}",
            headers=auth_headers,
            json={"name": "Brand New Name"},
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["name"] == "Brand New Name"
        assert data["description"] == "Original description"
        assert data["budget_usd"] == 50.0

    def test_update_empty_body(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: StandingChat,
    ) -> None:
        """Should succeed and do nothing when body is empty."""
        response = client.patch(
            f"/api/jobs/{test_agent.id}",
            headers=auth_headers,
            json={},
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["name"] == test_agent.name

    def test_rejects_invalid_cron(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: StandingChat,
    ) -> None:
        """Should return 400 for invalid cron expression."""
        response = client.patch(
            f"/api/jobs/{test_agent.id}",
            headers=auth_headers,
            json={"schedule": "bad cron"},
        )

        assert response.status_code == 400

    def test_returns_404_for_nonexistent(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for non-existent agent."""
        response = client.patch(
            "/api/jobs/nonexistent-id",
            headers=auth_headers,
            json={"name": "Test"},
        )

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.patch(
            "/api/jobs/some-agent-id",
            json={"name": "Test"},
        )
        assert response.status_code == 401


class TestDeleteAgent:
    """Tests for DELETE /api/jobs/<agent_id> endpoint."""

    def test_deletes_agent(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: StandingChat,
    ) -> None:
        """Should delete agent."""
        response = client.delete(
            f"/api/jobs/{test_agent.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200

        # Verify it's gone
        get_response = client.get(
            f"/api/jobs/{test_agent.id}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    def test_returns_404_for_nonexistent(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for non-existent agent."""
        response = client.delete(
            "/api/jobs/nonexistent-id",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.delete("/api/jobs/some-agent-id")
        assert response.status_code == 401


class TestTriggerAgent:
    """Tests for POST /api/jobs/<agent_id>/run endpoint."""

    @staticmethod
    def _fake_run(test_database: Any, status: str, error: str | None = None) -> Any:
        """run_job_now as the route sees it: one execution row, an outcome."""
        from src.agent.item_runner import RunOutcome

        def run(job: Any, user: Any, **kwargs: Any) -> RunOutcome:
            execution = test_database.create_execution(job.id, "manual")
            final = "failed" if status == "failed" else "completed"
            test_database.update_execution(execution.id, status=final, error_message=error)
            return RunOutcome(status, "Report", error=error)  # type: ignore[arg-type]

        return run

    def test_triggers_agent_execution(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: StandingChat,
        test_database: Any,
    ) -> None:
        """Should run the agent's standing job and return the execution record."""
        with patch(
            "src.api.routes.jobs.run_job_now", side_effect=self._fake_run(test_database, "report")
        ) as run:
            response = client.post(f"/api/jobs/{test_agent.id}/run", headers=auth_headers)

            assert response.status_code == 200
            data = json.loads(response.data)
            assert run.call_args.args[0].id == test_agent.id
            assert data["run"]["item_id"] == test_agent.id
            assert data["run"]["trigger_type"] == "manual"
            assert data["message"] == "Ran: the result is in its chat"

    def test_returns_failure_on_execution_error(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: StandingChat,
        test_database: Any,
    ) -> None:
        """Should return failure message on execution error."""
        with patch(
            "src.api.routes.jobs.run_job_now",
            side_effect=self._fake_run(test_database, "failed", "LLM error"),
        ):
            response = client.post(f"/api/jobs/{test_agent.id}/run", headers=auth_headers)

            assert response.status_code == 200
            data = json.loads(response.data)
            assert "LLM error" in data["message"]

    def test_returns_404_for_nonexistent(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for non-existent agent."""
        response = client.post(
            "/api/jobs/nonexistent-id/run",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.post("/api/jobs/some-agent-id/run")
        assert response.status_code == 401


class TestGetAgentExecutions:
    """Tests for GET /api/jobs/<agent_id>/runs endpoint."""

    def test_gets_execution_history(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: StandingChat,
        test_database: Database,
    ) -> None:
        """Should return agent execution history."""
        # Create some execution records
        test_database.create_execution(item_id=test_agent.id, trigger_type="manual")
        test_database.create_execution(item_id=test_agent.id, trigger_type="scheduled")

        response = client.get(
            f"/api/jobs/{test_agent.id}/runs",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "runs" in data
        assert len(data["runs"]) == 2

    def test_returns_empty_list_for_no_executions(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: StandingChat,
    ) -> None:
        """Should return empty list when no executions exist."""
        response = client.get(
            f"/api/jobs/{test_agent.id}/runs",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["runs"] == []

    def test_returns_404_for_nonexistent(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for non-existent agent."""
        response = client.get(
            "/api/jobs/nonexistent-id/runs",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/jobs/some-agent-id/runs")
        assert response.status_code == 401


def test_renaming_onto_an_existing_agent_name_is_a_validation_error(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Any, test_user: Any
) -> None:
    test_database.create_standing_chat(test_user.id, "Coach")
    other = test_database.create_standing_chat(test_user.id, "Watcher")

    response = client.patch(f"/api/jobs/{other.id}", headers=auth_headers, json={"name": "Coach"})

    assert response.status_code == 400
    assert test_database.get_standing_chat(other.id, test_user.id).name == "Watcher"


def test_write_toggle_sets_and_clears_the_level(
    client: FlaskClient, auth_headers: dict[str, str], test_agent: StandingChat
) -> None:
    """The editor's "can change things" toggle is the write level in grants."""
    url = f"/api/jobs/{test_agent.id}"

    on = client.patch(url, headers=auth_headers, json={"grants": ["todoist", "todoist:write"]})
    off = client.patch(url, headers=auth_headers, json={"grants": ["todoist"]})

    assert json.loads(on.data)["grants"] == ["todoist", "todoist:write"]
    assert json.loads(off.data)["grants"] == ["todoist"]


def test_editor_save_keeps_write_levels(
    client: FlaskClient, auth_headers: dict[str, str], test_agent: StandingChat
) -> None:
    """What GET shows, PATCH takes back unchanged: a save from the editor
    never drops a write level granted by an approval."""
    url = f"/api/jobs/{test_agent.id}"
    client.patch(url, headers=auth_headers, json={"grants": ["garmin_workout:write", "todoist"]})
    shown = json.loads(client.get(url, headers=auth_headers).data)

    saved = client.patch(url, headers=auth_headers, json={"grants": shown["grants"]})

    assert sorted(json.loads(saved.data)["grants"]) == ["garmin_workout:write", "todoist"]


def test_null_grants_leave_the_grants_alone(
    client: FlaskClient, auth_headers: dict[str, str], test_agent: StandingChat
) -> None:
    """A null in a PATCH never widens a job to all tools: "*" must be sent as such."""
    response = client.patch(
        f"/api/jobs/{test_agent.id}", headers=auth_headers, json={"grants": None}
    )

    assert json.loads(response.data)["grants"] == ["web_search"]
