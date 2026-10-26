"""Integration tests for the Command Center route (GET /api/agents/command-center)."""

import json
from typing import TYPE_CHECKING

from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Agent, Database


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
