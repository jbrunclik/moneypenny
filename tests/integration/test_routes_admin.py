"""Admin overview and the per-user spend status (S12)."""

from unittest.mock import patch

from flask.testing import FlaskClient

from src.config import Config
from src.db.models import Database, User


def _spend(db: Database, user: User, usd: float) -> None:
    conversation = db.create_conversation(user.id, "Chat")
    message = db.add_message(conversation.id, "assistant", "answer")
    db.save_message_cost(
        message_id=message.id,
        conversation_id=conversation.id,
        user_id=user.id,
        model="gemini-3.8-flash",
        input_tokens=10,
        output_tokens=10,
        cost_usd=usd,
        duration_ms=1200,
    )


class TestAdminOverviewAccess:
    def test_requires_a_token(self, client: FlaskClient) -> None:
        assert client.get("/api/admin/overview").status_code == 401

    def test_refuses_a_regular_user(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        with patch.object(Config, "ADMIN_EMAILS", ["someone-else@example.com"]):
            assert client.get("/api/admin/overview", headers=auth_headers).status_code == 403


class TestAdminOverviewContent:
    def _overview(self, client: FlaskClient, auth_headers: dict[str, str], test_user: User) -> dict:
        with patch.object(Config, "ADMIN_EMAILS", [test_user.email]):
            response = client.get("/api/admin/overview", headers=auth_headers)
        assert response.status_code == 200
        return response.get_json()

    def test_spend_per_user_and_totals(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        _spend(test_database, test_user, 12.5)
        data = self._overview(client, auth_headers, test_user)
        spend = data["spend"]
        assert spend["today"]["usd"] >= 12.5
        mine = next(u for u in spend["users"] if u["name"] == test_user.name)
        assert mine["today"]["usd"] >= 12.5
        assert mine["over_threshold"] is True
        assert len(spend["daily"]) == 30
        assert spend["by_feature"][0]["name"] == "chat"

    def test_every_section_is_present(
        self, client: FlaskClient, auth_headers: dict[str, str], test_user: User
    ) -> None:
        data = self._overview(client, auth_headers, test_user)
        assert set(data) >= {"spend", "agents", "search", "quality", "system", "currency"}
        assert {"runs_7d", "failed_7d", "pending_approvals", "recent_failures"} <= set(
            data["agents"]
        )
        assert data["search"]["providers"][-1]["provider"] == "ddgs"
        assert data["system"]["users"] >= 1

    def test_no_conversation_titles_or_content(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        conversation = test_database.create_conversation(test_user.id, "Secret family plans")
        test_database.add_message(conversation.id, "user", "private words")
        body = str(self._overview(client, auth_headers, test_user))
        assert "Secret family plans" not in body
        assert "private words" not in body


class TestSpendStatus:
    def test_under_the_threshold(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        _spend(test_database, test_user, 1.0)
        data = client.get("/api/users/me/spend-status", headers=auth_headers).get_json()
        assert data["over_threshold"] is False
        assert data["threshold_usd"] == Config.SPEND_WARNING_DAILY_USD

    def test_over_the_threshold(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        _spend(test_database, test_user, Config.SPEND_WARNING_DAILY_USD + 0.5)
        data = client.get("/api/users/me/spend-status", headers=auth_headers).get_json()
        assert data["over_threshold"] is True
        assert data["today"]["formatted"]

    def test_requires_a_token(self, client: FlaskClient) -> None:
        assert client.get("/api/users/me/spend-status").status_code == 401
