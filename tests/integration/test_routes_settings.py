"""Integration tests for settings API endpoints."""

from typing import Any, ClassVar

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

    BRIEFING: ClassVar[dict[str, Any]] = {
        "enabled": True,
        "time": "07:30",
        "timezone": "Europe/Prague",
    }

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
        assert user.daily_briefing_job_id is not None
        agent = test_database.get_standing_chat(user.daily_briefing_job_id, user.id)
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
        agent = test_database.get_standing_chat(user.daily_briefing_job_id, user.id)
        assert agent.schedule == "15 21 * * *"
        # Same agent reused, not a duplicate
        agents = test_database.list_standing_chats(user.id)
        assert len([a for a in agents if a.name == "Daily Briefing"]) == 1

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
        agent = test_database.get_standing_chat(user.daily_briefing_job_id, user.id)
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
        assert user.daily_briefing_job_id is None

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
        first_agent_id = user.daily_briefing_job_id
        # User deletes the agent from Command Center
        test_database.delete_standing_chat(first_agent_id, user.id)

        briefing = client.get("/api/users/me/settings", headers=auth_headers).get_json()[
            "daily_briefing"
        ]
        assert briefing["enabled"] is False

        # Re-enabling creates a fresh agent
        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"daily_briefing": self.BRIEFING}
        )
        user = test_database.get_user_by_id(test_user.id)
        assert user.daily_briefing_job_id is not None
        assert user.daily_briefing_job_id != first_agent_id

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
            effective_instructions,
        )

        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"daily_briefing": self.BRIEFING}
        )
        user = test_database.get_user_by_id(test_user.id)
        agent = test_database.get_standing_chat(user.daily_briefing_job_id, user.id)

        assert agent.standing_type == SYSTEM_TYPE_DAILY_BRIEFING
        assert agent.instructions is None
        assert (
            effective_instructions(agent.instructions, agent.standing_type)
            == BRIEFING_SYSTEM_PROMPT
        )

        # A customized prompt wins and survives settings re-saves
        test_database.update_standing_chat(
            agent.id, user.id, instructions="My custom briefing style"
        )
        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"daily_briefing": self.BRIEFING}
        )
        agent = test_database.get_standing_chat(agent.id, user.id)
        assert agent.instructions == "My custom briefing style"
        assert effective_instructions(agent.instructions, agent.standing_type) == (
            "My custom briefing style"
        )

    def test_job_detail_exposes_standing_type_and_effective_instructions(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user,
        test_database,
    ) -> None:
        from src.agent.daily_briefing import BRIEFING_SYSTEM_PROMPT

        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"daily_briefing": self.BRIEFING}
        )
        job_id = test_database.get_user_by_id(test_user.id).daily_briefing_job_id
        briefing = client.get(f"/api/jobs/{job_id}", headers=auth_headers).get_json()
        assert briefing["standing_type"] == "daily_briefing"
        assert briefing["instructions"] is None
        assert briefing["effective_instructions"] == BRIEFING_SYSTEM_PROMPT

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
        test_database.update_standing_chat(user.daily_briefing_job_id, user.id, grants=[])
        assert test_database.get_standing_chat(user.daily_briefing_job_id, user.id).grants == []

        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"daily_briefing": self.BRIEFING}
        )
        agent = test_database.get_standing_chat(user.daily_briefing_job_id, user.id)
        assert agent.grants == ["*"]

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
        agent_id = user.daily_briefing_job_id

        update = client.patch(
            f"/api/jobs/{agent_id}",
            headers=auth_headers,
            json={"description": "hijack"},
        )
        assert update.status_code == 400
        assert "Settings" in update.get_json()["error"]["message"]

        delete = client.delete(f"/api/jobs/{agent_id}", headers=auth_headers)
        assert delete.status_code == 400
        assert test_database.get_standing_chat(agent_id, user.id) is not None

        # Settings untoggle still works (disables, keeps history)
        client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"daily_briefing": {**self.BRIEFING, "enabled": False}},
        )
        assert test_database.get_standing_chat(agent_id, user.id).enabled is False


class TestPreferredLanguage:
    def test_round_trip_and_clear(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        # Default: auto
        assert (
            client.get("/api/users/me/settings", headers=auth_headers).get_json()[
                "preferred_language"
            ]
            is None
        )

        response = client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"preferred_language": "Czech"},
        )
        assert response.status_code == 200
        assert (
            client.get("/api/users/me/settings", headers=auth_headers).get_json()[
                "preferred_language"
            ]
            == "Czech"
        )

        # Empty string clears back to auto
        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"preferred_language": ""}
        )
        assert (
            client.get("/api/users/me/settings", headers=auth_headers).get_json()[
                "preferred_language"
            ]
            is None
        )

    def test_language_section_in_user_context(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user,
        test_database,
        monkeypatch,
    ) -> None:
        from src.agent import prompts

        client.patch(
            "/api/users/me/settings",
            headers=auth_headers,
            json={"preferred_language": "Czech"},
        )
        monkeypatch.setattr(prompts, "db", test_database)
        context = prompts.get_user_context(test_user.name, test_user.id)
        assert "primary language is Czech" in context

        # Auto -> no language section
        client.patch(
            "/api/users/me/settings", headers=auth_headers, json={"preferred_language": ""}
        )
        context = prompts.get_user_context(test_user.name, test_user.id)
        assert "primary language" not in context
