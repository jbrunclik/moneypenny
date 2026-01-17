"""Integration tests for autonomous agent routes."""

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Agent, Database


class TestListAgents:
    """Tests for GET /api/agents endpoint."""

    def test_lists_user_agents(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should return list of user's agents."""
        response = client.get("/api/agents", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "agents" in data
        assert len(data["agents"]) >= 1
        assert any(a["id"] == test_agent.id for a in data["agents"])

    def test_includes_agent_details(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should include agent details in response."""
        response = client.get("/api/agents", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        agent = next(a for a in data["agents"] if a["id"] == test_agent.id)

        assert agent["name"] == "Test Agent"
        assert agent["description"] == "A test agent for integration tests"
        assert agent["system_prompt"] == "You are a helpful test agent."
        assert agent["schedule"] == "0 9 * * *"
        assert agent["timezone"] == "UTC"
        assert agent["enabled"] is True
        assert "unread_count" in agent
        assert "has_pending_approval" in agent

    def test_returns_empty_list_for_new_user(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return empty list when user has no agents."""
        response = client.get("/api/agents", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["agents"] == []

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/agents")
        assert response.status_code == 401


class TestCreateAgent:
    """Tests for POST /api/agents endpoint."""

    def test_creates_agent(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should create new agent."""
        response = client.post(
            "/api/agents",
            headers=auth_headers,
            json={"name": "New Agent"},
        )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert "id" in data
        assert data["name"] == "New Agent"
        assert data["timezone"] == "UTC"  # Default
        assert data["enabled"] is True  # Default

    def test_creates_with_all_fields(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should create agent with all optional fields."""
        response = client.post(
            "/api/agents",
            headers=auth_headers,
            json={
                "name": "Full Agent",
                "description": "A fully configured agent",
                "system_prompt": "You are helpful",
                "schedule": "0 9 * * 1-5",
                "timezone": "America/New_York",
                "tool_permissions": ["web_search", "todoist"],
                "enabled": False,
            },
        )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["name"] == "Full Agent"
        assert data["description"] == "A fully configured agent"
        assert data["schedule"] == "0 9 * * 1-5"
        assert data["timezone"] == "America/New_York"
        assert data["enabled"] is False

    def test_rejects_invalid_cron(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should return 400 for invalid cron expression."""
        response = client.post(
            "/api/agents",
            headers=auth_headers,
            json={"name": "Bad Cron Agent", "schedule": "invalid cron"},
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_rejects_invalid_timezone(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 400 for invalid timezone."""
        response = client.post(
            "/api/agents",
            headers=auth_headers,
            json={"name": "Bad TZ Agent", "timezone": "Invalid/Timezone"},
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_rejects_duplicate_name(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should return 400 for duplicate agent name."""
        response = client.post(
            "/api/agents",
            headers=auth_headers,
            json={"name": "Test Agent"},  # Same name as test_agent
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "already exists" in data["error"]["message"]

    def test_rejects_empty_name(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should return 400 for empty name."""
        response = client.post(
            "/api/agents",
            headers=auth_headers,
            json={"name": ""},
        )

        # Pydantic validation rejects empty string with 422 status
        assert response.status_code in [400, 422]

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.post("/api/agents", json={"name": "Test"})
        assert response.status_code == 401


class TestGetAgent:
    """Tests for GET /api/agents/<agent_id> endpoint."""

    def test_gets_agent(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should return agent details."""
        response = client.get(
            f"/api/agents/{test_agent.id}",
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
            "/api/agents/nonexistent-id",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_returns_404_for_other_users_agent(
        self,
        client: FlaskClient,
        test_database: Database,
        test_agent: Agent,
    ) -> None:
        """Should return 404 when accessing another user's agent."""
        # Create another user
        other_user = test_database.get_or_create_user(email="other@example.com", name="Other")

        # Get a token for the other user
        from src.auth.jwt_auth import create_token

        other_token = create_token(other_user)

        response = client.get(
            f"/api/agents/{test_agent.id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient, test_agent: Agent) -> None:
        """Should return 401 without authentication."""
        response = client.get(f"/api/agents/{test_agent.id}")
        assert response.status_code == 401


class TestUpdateAgent:
    """Tests for PATCH /api/agents/<agent_id> endpoint."""

    def test_updates_name(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should update agent name."""
        response = client.patch(
            f"/api/agents/{test_agent.id}",
            headers=auth_headers,
            json={"name": "Updated Agent Name"},
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["name"] == "Updated Agent Name"

    def test_updates_multiple_fields(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should update multiple fields at once."""
        response = client.patch(
            f"/api/agents/{test_agent.id}",
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
        test_agent: Agent,
    ) -> None:
        """Should clear schedule by setting to empty string."""
        response = client.patch(
            f"/api/agents/{test_agent.id}",
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
        test_agent: Agent,
    ) -> None:
        """Should clear tool permissions by setting to empty list."""
        # First set some permissions
        client.patch(
            f"/api/agents/{test_agent.id}",
            headers=auth_headers,
            json={"tool_permissions": ["web_search"]},
        )

        # Now clear them
        response = client.patch(
            f"/api/agents/{test_agent.id}",
            headers=auth_headers,
            json={"tool_permissions": []},
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["tool_permissions"] == []

    def test_clears_budget_limit(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should clear budget limit by setting to null."""
        # First set a limit
        client.patch(
            f"/api/agents/{test_agent.id}",
            headers=auth_headers,
            json={"budget_limit": 10.0},
        )

        # Now clear it (set to null)
        response = client.patch(
            f"/api/agents/{test_agent.id}",
            headers=auth_headers,
            json={"budget_limit": None},
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["budget_limit"] is None

    def test_partial_update_preserves_other_fields(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should only update provided fields and preserve others."""
        # Set initial state
        client.patch(
            f"/api/agents/{test_agent.id}",
            headers=auth_headers,
            json={
                "description": "Original description",
                "budget_limit": 50.0,
            },
        )

        # Update only name
        response = client.patch(
            f"/api/agents/{test_agent.id}",
            headers=auth_headers,
            json={"name": "Brand New Name"},
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["name"] == "Brand New Name"
        assert data["description"] == "Original description"
        assert data["budget_limit"] == 50.0

    def test_update_empty_body(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should succeed and do nothing when body is empty."""
        response = client.patch(
            f"/api/agents/{test_agent.id}",
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
        test_agent: Agent,
    ) -> None:
        """Should return 400 for invalid cron expression."""
        response = client.patch(
            f"/api/agents/{test_agent.id}",
            headers=auth_headers,
            json={"schedule": "bad cron"},
        )

        assert response.status_code == 400

    def test_returns_404_for_nonexistent(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for non-existent agent."""
        response = client.patch(
            "/api/agents/nonexistent-id",
            headers=auth_headers,
            json={"name": "Test"},
        )

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.patch(
            "/api/agents/some-agent-id",
            json={"name": "Test"},
        )
        assert response.status_code == 401


class TestDeleteAgent:
    """Tests for DELETE /api/agents/<agent_id> endpoint."""

    def test_deletes_agent(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should delete agent."""
        response = client.delete(
            f"/api/agents/{test_agent.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200

        # Verify it's gone
        get_response = client.get(
            f"/api/agents/{test_agent.id}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    def test_returns_404_for_nonexistent(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for non-existent agent."""
        response = client.delete(
            "/api/agents/nonexistent-id",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.delete("/api/agents/some-agent-id")
        assert response.status_code == 401


class TestTriggerAgent:
    """Tests for POST /api/agents/<agent_id>/run endpoint."""

    def test_triggers_agent_execution(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should trigger agent and return execution record."""
        # Mock the execute_agent function to avoid actual LLM calls
        with patch("src.agent.executor.execute_agent") as mock_execute:
            mock_execute.return_value = (True, None)

            response = client.post(
                f"/api/agents/{test_agent.id}/run",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = json.loads(response.data)
            assert "execution" in data
            assert data["execution"]["agent_id"] == test_agent.id
            assert data["execution"]["trigger_type"] == "manual"
            assert data["message"] == "Agent executed successfully"

    def test_returns_failure_on_execution_error(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should return failure message on execution error."""
        with patch("src.agent.executor.execute_agent") as mock_execute:
            mock_execute.return_value = (False, "LLM error")

            response = client.post(
                f"/api/agents/{test_agent.id}/run",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = json.loads(response.data)
            assert "LLM error" in data["message"]

    def test_returns_404_for_nonexistent(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for non-existent agent."""
        response = client.post(
            "/api/agents/nonexistent-id/run",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.post("/api/agents/some-agent-id/run")
        assert response.status_code == 401


class TestGetAgentExecutions:
    """Tests for GET /api/agents/<agent_id>/executions endpoint."""

    def test_gets_execution_history(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
        test_database: Database,
    ) -> None:
        """Should return agent execution history."""
        # Create some execution records
        test_database.create_execution(agent_id=test_agent.id, trigger_type="manual")
        test_database.create_execution(agent_id=test_agent.id, trigger_type="scheduled")

        response = client.get(
            f"/api/agents/{test_agent.id}/executions",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "executions" in data
        assert len(data["executions"]) == 2

    def test_returns_empty_list_for_no_executions(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should return empty list when no executions exist."""
        response = client.get(
            f"/api/agents/{test_agent.id}/executions",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["executions"] == []

    def test_returns_404_for_nonexistent(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for non-existent agent."""
        response = client.get(
            "/api/agents/nonexistent-id/executions",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/agents/some-agent-id/executions")
        assert response.status_code == 401


class TestCommandCenter:
    """Tests for GET /api/agents/command-center endpoint."""

    def test_gets_command_center_data(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should return command center dashboard data."""
        response = client.get("/api/agents/command-center", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "agents" in data
        assert "pending_approvals" in data
        assert "recent_executions" in data
        assert "total_unread" in data
        assert "agents_waiting" in data

    def test_includes_agent_in_command_center(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should include test agent in command center agents list."""
        response = client.get("/api/agents/command-center", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert any(a["id"] == test_agent.id for a in data["agents"])

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/agents/command-center")
        assert response.status_code == 401

    def test_includes_agents_with_errors_count(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should include agents_with_errors count in response."""
        response = client.get("/api/agents/command-center", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "agents_with_errors" in data
        assert isinstance(data["agents_with_errors"], int)

    def test_agent_fields_in_response(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
    ) -> None:
        """Should include all expected fields for each agent."""
        response = client.get("/api/agents/command-center", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        agent = next(a for a in data["agents"] if a["id"] == test_agent.id)

        # Verify required fields
        required_fields = [
            "id",
            "name",
            "schedule",
            "timezone",
            "enabled",
            "has_pending_approval",
            "has_error",
            "unread_count",
            "created_at",
            "updated_at",
            "model",
        ]
        for field in required_fields:
            assert field in agent, f"Missing field: {field}"

    def test_recent_executions_fields(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_agent: Agent,
        test_database: Database,
    ) -> None:
        """Should include all expected fields in recent_executions."""
        # Create an execution record
        execution = test_database.create_execution(
            agent_id=test_agent.id,
            trigger_type="manual",
        )
        test_database.update_execution(execution.id, status="completed")

        response = client.get("/api/agents/command-center", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["recent_executions"]) > 0

        exec_record = data["recent_executions"][0]
        required_fields = ["id", "agent_id", "status", "trigger_type", "started_at"]
        for field in required_fields:
            assert field in exec_record, f"Missing field: {field}"

    def test_empty_command_center(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should return valid response for user with no agents."""
        response = client.get("/api/agents/command-center", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["agents"] == []
        assert data["pending_approvals"] == []
        assert data["recent_executions"] == []
        assert data["total_unread"] == 0
        assert data["agents_waiting"] == 0
        assert data["agents_with_errors"] == 0
