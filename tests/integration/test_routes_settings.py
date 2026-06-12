"""Integration tests for settings API endpoints."""

from flask.testing import FlaskClient


class TestGetUserSettings:
    """Tests for GET /api/users/me/settings."""

    def test_get_settings_returns_empty_for_new_user(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """New users should have empty custom instructions."""
        response = client.get("/api/users/me/settings", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["custom_instructions"] == ""

    def test_get_settings_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/users/me/settings")

        assert response.status_code == 401


class TestUpdateUserSettings:
    """Tests for PATCH /api/users/me/settings."""

    def test_update_custom_instructions(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should save custom instructions."""
        response = client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"custom_instructions": "Respond in Czech."},
        )

        assert response.status_code == 200
        assert response.get_json()["status"] == "updated"

        # Verify the instructions were saved
        get_response = client.get("/api/users/me/settings", headers=auth_headers)
        assert get_response.get_json()["custom_instructions"] == "Respond in Czech."

    def test_update_custom_instructions_empty_string(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Empty string should clear instructions."""
        # First set some instructions
        client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"custom_instructions": "Be concise."},
        )

        # Then clear them
        response = client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"custom_instructions": ""},
        )

        assert response.status_code == 200

        # Verify they were cleared
        get_response = client.get("/api/users/me/settings", headers=auth_headers)
        assert get_response.get_json()["custom_instructions"] == ""

    def test_update_custom_instructions_whitespace_only(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Whitespace-only string should be normalized to empty."""
        # First set some instructions
        client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"custom_instructions": "Be concise."},
        )

        # Then set whitespace-only
        response = client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"custom_instructions": "   \n\t  "},
        )

        assert response.status_code == 200

        # Verify they were cleared
        get_response = client.get("/api/users/me/settings", headers=auth_headers)
        assert get_response.get_json()["custom_instructions"] == ""

    def test_update_custom_instructions_max_length(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should reject instructions exceeding 2000 characters."""
        long_instructions = "x" * 2001

        response = client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"custom_instructions": long_instructions},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_update_custom_instructions_at_max_length(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should accept instructions at exactly 2000 characters."""
        max_instructions = "x" * 2000

        response = client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"custom_instructions": max_instructions},
        )

        assert response.status_code == 200

        # Verify they were saved
        get_response = client.get("/api/users/me/settings", headers=auth_headers)
        assert get_response.get_json()["custom_instructions"] == max_instructions

    def test_update_custom_instructions_null_value(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Null value should not change instructions (PATCH semantics)."""
        # First set some instructions
        client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"custom_instructions": "Be concise."},
        )

        # Send null - should not change
        response = client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"custom_instructions": None},
        )

        assert response.status_code == 200

        # Verify instructions unchanged (null means "don't update this field")
        get_response = client.get("/api/users/me/settings", headers=auth_headers)
        assert get_response.get_json()["custom_instructions"] == "Be concise."

    def test_update_settings_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.patch(
            "/api/users/me/settings",
            json={"custom_instructions": "Be concise."},
        )

        assert response.status_code == 401

    def test_update_empty_body(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Empty body should be valid (no changes)."""
        response = client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={},
        )

        assert response.status_code == 200


class TestDailyBriefingSettings:
    """Daily Briefing opt-in via settings (backed by a system agent)."""

    BRIEFING = {"enabled": True, "time": "07:30", "timezone": "Europe/Prague"}

    def test_defaults_disabled(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        response = client.get("/api/users/me/settings", headers=auth_headers)
        assert response.status_code == 200
        briefing = response.get_json()["daily_briefing"]
        assert briefing == {"enabled": False, "time": "08:00", "timezone": "UTC"}

    def test_enable_creates_agent(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user,
        test_database,
    ) -> None:
        response = client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"daily_briefing": self.BRIEFING},
        )
        assert response.status_code == 200

        user = test_database.get_user_by_id(test_user.id)
        assert user.daily_briefing_agent_id is not None
        agent = test_database.get_agent(user.daily_briefing_agent_id, user.id)
        assert agent is not None
        assert agent.name == "Daily Briefing"
        assert agent.schedule == "30 7 * * *"
        assert agent.timezone == "Europe/Prague"
        assert agent.enabled is True
        assert agent.next_run_at is not None

        # GET reflects the stored state
        get_response = client.get("/api/users/me/settings", headers=auth_headers)
        assert get_response.get_json()["daily_briefing"] == self.BRIEFING

    def test_time_change_updates_schedule(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user,
        test_database,
    ) -> None:
        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"daily_briefing": self.BRIEFING}
        )
        client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"daily_briefing": {**self.BRIEFING, "time": "21:15"}},
        )

        user = test_database.get_user_by_id(test_user.id)
        agent = test_database.get_agent(user.daily_briefing_agent_id, user.id)
        assert agent.schedule == "15 21 * * *"
        # Same agent reused, not a duplicate
        assert (
            len([a for a in test_database.list_agents(user.id) if a.name == "Daily Briefing"]) == 1
        )

    def test_disable_keeps_agent_disabled(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user,
        test_database,
    ) -> None:
        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"daily_briefing": self.BRIEFING}
        )
        client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"daily_briefing": {**self.BRIEFING, "enabled": False}},
        )

        user = test_database.get_user_by_id(test_user.id)
        agent = test_database.get_agent(user.daily_briefing_agent_id, user.id)
        assert agent.enabled is False

        briefing = client.get("/api/users/me/settings", headers=auth_headers).get_json()[
            "daily_briefing"
        ]
        assert briefing["enabled"] is False
        assert briefing["time"] == "07:30"

    def test_disable_without_agent_is_noop(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user,
        test_database,
    ) -> None:
        response = client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"daily_briefing": {"enabled": False, "time": "08:00", "timezone": "UTC"}},
        )
        assert response.status_code == 200
        user = test_database.get_user_by_id(test_user.id)
        assert user.daily_briefing_agent_id is None

    def test_dangling_agent_id_reports_disabled_and_recreates(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user,
        test_database,
    ) -> None:
        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"daily_briefing": self.BRIEFING}
        )
        user = test_database.get_user_by_id(test_user.id)
        first_agent_id = user.daily_briefing_agent_id
        # User deletes the agent from Command Center
        test_database.delete_agent(first_agent_id, user.id)

        briefing = client.get("/api/users/me/settings", headers=auth_headers).get_json()[
            "daily_briefing"
        ]
        assert briefing["enabled"] is False

        # Re-enabling creates a fresh agent
        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"daily_briefing": self.BRIEFING}
        )
        user = test_database.get_user_by_id(test_user.id)
        assert user.daily_briefing_agent_id is not None
        assert user.daily_briefing_agent_id != first_agent_id

    def test_invalid_time_rejected(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        response = client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"daily_briefing": {"enabled": True, "time": "25:00", "timezone": "UTC"}},
        )
        assert response.status_code == 400

    def test_stock_prompt_lives_in_code_not_db(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user,
        test_database,
    ) -> None:
        """The briefing agent stores NULL while on the stock prompt; the
        runtime resolver supplies the current default from code, so
        prompt improvements need no migration or user action."""
        from src.agent.daily_briefing import (
            BRIEFING_SYSTEM_PROMPT,
            SYSTEM_TYPE_DAILY_BRIEFING,
            resolve_agent_system_prompt,
        )

        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"daily_briefing": self.BRIEFING}
        )
        user = test_database.get_user_by_id(test_user.id)
        agent = test_database.get_agent(user.daily_briefing_agent_id, user.id)

        assert agent.system_type == SYSTEM_TYPE_DAILY_BRIEFING
        assert agent.system_prompt is None
        assert resolve_agent_system_prompt(agent) == BRIEFING_SYSTEM_PROMPT

        # A customized prompt wins and survives settings re-saves
        test_database.update_agent(agent.id, user.id, system_prompt="My custom briefing style")
        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"daily_briefing": self.BRIEFING}
        )
        agent = test_database.get_agent(agent.id, user.id)
        assert agent.system_prompt == "My custom briefing style"
        assert resolve_agent_system_prompt(agent) == "My custom briefing style"

    def test_agent_response_exposes_system_type_and_effective_prompt(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        from src.agent.daily_briefing import BRIEFING_SYSTEM_PROMPT

        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"daily_briefing": self.BRIEFING}
        )
        agents = client.get("/api/agents", headers=auth_headers).get_json()["agents"]
        briefing = next(a for a in agents if a["name"] == "Daily Briefing")
        assert briefing["system_type"] == "daily_briefing"
        assert briefing["system_prompt"] is None
        assert briefing["effective_system_prompt"] == BRIEFING_SYSTEM_PROMPT

    def test_settings_save_restores_unrestricted_tools(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user,
        test_database,
    ) -> None:
        """The old editor trap stored '[]' (no integrations) on the
        briefing agent; a settings save restores unrestricted tools."""
        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"daily_briefing": self.BRIEFING}
        )
        user = test_database.get_user_by_id(test_user.id)
        test_database.update_agent(user.daily_briefing_agent_id, user.id, tool_permissions=[])
        assert test_database.get_agent(user.daily_briefing_agent_id, user.id).tool_permissions == []

        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"daily_briefing": self.BRIEFING}
        )
        agent = test_database.get_agent(user.daily_briefing_agent_id, user.id)
        assert agent.tool_permissions is None

    def test_system_agent_cannot_be_edited_or_deleted_via_api(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user,
        test_database,
    ) -> None:
        """Built-in agents are purely system-managed: the agents API
        rejects edits and deletion; lifecycle goes through Settings."""
        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"daily_briefing": self.BRIEFING}
        )
        user = test_database.get_user_by_id(test_user.id)
        agent_id = user.daily_briefing_agent_id

        update = client.patch(
            f"/api/agents/{agent_id}",
            headers=auth_headers,
            json={"description": "hijack"},
        )
        assert update.status_code == 400
        assert "Settings" in update.get_json()["error"]["message"]

        delete = client.delete(f"/api/agents/{agent_id}", headers=auth_headers)
        assert delete.status_code == 400
        assert test_database.get_agent(agent_id, user.id) is not None

        # Settings untoggle still works (disables, keeps history)
        client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"daily_briefing": {**self.BRIEFING, "enabled": False}},
        )
        assert test_database.get_agent(agent_id, user.id).enabled is False
