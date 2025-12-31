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
