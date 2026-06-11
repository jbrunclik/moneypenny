"""Integration tests for Todoist OAuth routes (T2), including S7 state checks."""

from unittest.mock import patch

from flask.testing import FlaskClient

from src.db.models import Database, User


class TestTodoistAuthUrl:
    def test_returns_url_and_state(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        with patch("src.api.routes.todoist.get_authorization_url") as mock_url:
            mock_url.return_value = "https://app.todoist.com/oauth/authorize?..."
            response = client.get("/auth/todoist/auth-url", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert "auth_url" in data
        assert "state" in data
        # The state passed to the provider URL is the issued one
        mock_url.assert_called_once_with(data["state"])

    def test_requires_auth(self, client: FlaskClient) -> None:
        assert client.get("/auth/todoist/auth-url").status_code == 401


class TestTodoistConnect:
    def _issued_state(self, test_user: User) -> str:
        from src.auth.oauth_state import issue_state

        return issue_state(test_user.id, "todoist")

    def test_connect_success(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        state = self._issued_state(test_user)
        with (
            patch("src.api.routes.todoist.exchange_code_for_token") as mock_exchange,
            patch("src.api.routes.todoist.get_todoist_user_info") as mock_info,
        ):
            mock_exchange.return_value = "todoist-access-token"
            mock_info.return_value = {"email": "user@example.com"}
            response = client.post(
                "/auth/todoist/connect",
                headers=auth_headers,
                json={"code": "test-code", "state": state},
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["connected"] is True
        assert data["todoist_email"] == "user@example.com"
        # Token persisted
        user = test_database.get_user_by_id(test_user.id)
        assert user.todoist_access_token == "todoist-access-token"

    def test_connect_rejects_unknown_state(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """A state the server never issued must be rejected (S7)."""
        with patch("src.api.routes.todoist.exchange_code_for_token") as mock_exchange:
            response = client.post(
                "/auth/todoist/connect",
                headers=auth_headers,
                json={"code": "test-code", "state": "forged-state"},
            )

        assert response.status_code == 400
        mock_exchange.assert_not_called()

    def test_connect_state_is_single_use(
        self, client: FlaskClient, auth_headers: dict[str, str], test_user: User
    ) -> None:
        state = self._issued_state(test_user)
        with (
            patch("src.api.routes.todoist.exchange_code_for_token", return_value="tok"),
            patch(
                "src.api.routes.todoist.get_todoist_user_info",
                return_value={"email": "u@example.com"},
            ),
        ):
            first = client.post(
                "/auth/todoist/connect",
                headers=auth_headers,
                json={"code": "test-code", "state": state},
            )
            replay = client.post(
                "/auth/todoist/connect",
                headers=auth_headers,
                json={"code": "test-code", "state": state},
            )

        assert first.status_code == 200
        assert replay.status_code == 400

    def test_connect_exchange_failure(
        self, client: FlaskClient, auth_headers: dict[str, str], test_user: User
    ) -> None:
        from src.auth.todoist_auth import TodoistAuthError

        state = self._issued_state(test_user)
        with patch("src.api.routes.todoist.exchange_code_for_token") as mock_exchange:
            mock_exchange.side_effect = TodoistAuthError("Exchange failed")
            response = client.post(
                "/auth/todoist/connect",
                headers=auth_headers,
                json={"code": "bad-code", "state": state},
            )

        assert response.status_code == 400

    def test_connect_requires_auth(self, client: FlaskClient) -> None:
        response = client.post("/auth/todoist/connect", json={"code": "c", "state": "s"})
        assert response.status_code == 401


class TestTodoistDisconnect:
    def test_disconnect_clears_token(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        test_database.update_user_todoist_token(test_user.id, "some-token")

        response = client.post("/auth/todoist/disconnect", headers=auth_headers)

        assert response.status_code == 200
        assert test_database.get_user_by_id(test_user.id).todoist_access_token is None


class TestTodoistStatus:
    def test_status_disconnected(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        response = client.get("/auth/todoist/status", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json()["connected"] is False
