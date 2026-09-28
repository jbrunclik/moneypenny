"""Integration tests for cost tracking routes."""

import json
from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, User


class TestGetConversationCost:
    """Tests for GET /api/conversations/<conv_id>/cost endpoint."""

    def test_returns_conversation_cost(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return total cost for conversation."""
        # Add messages with costs
        msg1 = test_database.add_message(test_conversation.id, "assistant", "R1")
        msg2 = test_database.add_message(test_conversation.id, "assistant", "R2")
        test_database.save_message_cost(
            msg1.id, test_conversation.id, test_user.id, "gemini-3-flash-preview", 100, 50, 0.01
        )
        test_database.save_message_cost(
            msg2.id, test_conversation.id, test_user.id, "gemini-3-flash-preview", 200, 100, 0.02
        )

        response = client.get(
            f"/api/conversations/{test_conversation.id}/cost",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "cost_usd" in data
        assert data["cost_usd"] == pytest.approx(0.03)

    def test_returns_zero_for_no_costs(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return 0 when no cost data exists."""
        response = client.get(
            f"/api/conversations/{test_conversation.id}/cost",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["cost_usd"] == 0.0

    def test_returns_404_for_nonexistent_conversation(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for non-existent conversation."""
        response = client.get(
            "/api/conversations/nonexistent-id/cost",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient, test_conversation: Conversation) -> None:
        """Should return 401 without authentication."""
        response = client.get(f"/api/conversations/{test_conversation.id}/cost")
        assert response.status_code == 401


class TestGetMessageCost:
    """Tests for GET /api/messages/<message_id>/cost endpoint."""

    def test_returns_message_cost(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return cost details for specific message."""
        msg = test_database.add_message(test_conversation.id, "assistant", "Response")
        test_database.save_message_cost(
            msg.id,
            test_conversation.id,
            test_user.id,
            "gemini-3-flash-preview",
            1000,
            500,
            0.05,
            image_generation_cost_usd=0.02,
        )

        response = client.get(
            f"/api/messages/{msg.id}/cost",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["cost_usd"] == pytest.approx(0.05)
        assert data["input_tokens"] == 1000
        assert data["output_tokens"] == 500
        assert data["model"] == "gemini-3-flash-preview"
        assert data["image_generation_cost_usd"] == pytest.approx(0.02)

    def test_returns_404_for_no_cost_data(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should return 404 when message has no cost data."""
        msg = test_database.add_message(test_conversation.id, "assistant", "Response")

        response = client.get(
            f"/api/messages/{msg.id}/cost",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_requires_auth(
        self,
        client: FlaskClient,
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should return 401 without authentication."""
        msg = test_database.add_message(test_conversation.id, "assistant", "R")

        response = client.get(f"/api/messages/{msg.id}/cost")
        assert response.status_code == 401


class TestGetMonthlyCost:
    """Tests for GET /api/users/me/costs/monthly endpoint."""

    def test_returns_current_month_cost(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return cost for current month."""
        msg = test_database.add_message(test_conversation.id, "assistant", "R1")
        test_database.save_message_cost(
            msg.id, test_conversation.id, test_user.id, "gemini-3-flash-preview", 100, 50, 0.05
        )

        response = client.get(
            "/api/users/me/costs/monthly",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "total_usd" in data
        assert "message_count" in data
        assert data["total_usd"] >= 0.05
        assert data["message_count"] >= 1

    def test_returns_zero_for_no_data(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 0 when no cost data exists."""
        response = client.get(
            "/api/users/me/costs/monthly",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["total_usd"] == 0.0
        assert data["message_count"] == 0

    def test_accepts_year_month_params(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should accept year and month query parameters."""
        now = datetime.now()

        response = client.get(
            f"/api/users/me/costs/monthly?year={now.year}&month={now.month}",
            headers=auth_headers,
        )

        assert response.status_code == 200

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/users/me/costs/monthly")
        assert response.status_code == 401


class TestGetCostHistory:
    """Tests for GET /api/users/me/costs/history endpoint."""

    def test_returns_cost_history(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return monthly cost history."""
        msg = test_database.add_message(test_conversation.id, "assistant", "R1")
        test_database.save_message_cost(
            msg.id, test_conversation.id, test_user.id, "gemini-3-flash-preview", 100, 50, 0.05
        )

        response = client.get(
            "/api/users/me/costs/history",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "history" in data
        assert isinstance(data["history"], list)
        # Should have at least current month
        if data["history"]:
            assert "year" in data["history"][0]
            assert "month" in data["history"][0]
            assert "total_usd" in data["history"][0]

    def test_returns_current_month_with_zero_cost(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should always include current month (with zero cost if no data)."""
        response = client.get(
            "/api/users/me/costs/history",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        # API always includes current month, even with no cost data
        assert len(data["history"]) >= 1
        now = datetime.now()
        assert data["history"][0]["year"] == now.year
        assert data["history"][0]["month"] == now.month
        assert data["history"][0]["total_usd"] == 0.0
        assert data["history"][0]["message_count"] == 0

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/users/me/costs/history")
        assert response.status_code == 401


class TestGetConversationCompaction:
    """Tests for GET /api/conversations/<conv_id>/compaction endpoint."""

    @pytest.fixture(autouse=True)
    def _compaction_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.config import Config

        monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_ENABLED", True)
        monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_THRESHOLD", 10)
        monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_KEEP_RECENT", 4)
        monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_RESUMMARIZE_BATCH", 5)

    @staticmethod
    def _add_messages(db: Database, conv_id: str, n: int) -> list[str]:
        return [
            db.add_message(conv_id, "user" if i % 2 == 0 else "assistant", f"m{i}").id
            for i in range(n)
        ]

    def test_reports_active_compaction(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should describe the summary the next turn sends the model."""
        from src.agent.conversation_compaction import KV_NAMESPACE

        ids = self._add_messages(test_database, test_conversation.id, 20)
        test_database.kv_set(
            test_user.id,
            KV_NAMESPACE,
            test_conversation.id,
            json.dumps({"summary": "Earlier: hotels", "covered_count": 12, "generation": 3}),
        )

        response = client.get(
            f"/api/conversations/{test_conversation.id}/compaction",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert json.loads(response.data) == {
            "conversation_id": test_conversation.id,
            "active": True,
            "summarized_count": 12,
            "total_count": 20,
            "generation": 3,
            "generation_estimated": False,
            "boundary_message_id": ids[11],
            "summary": "Earlier: hotels",
        }

    def test_inactive_without_summary(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should report inactive when the history is still sent verbatim."""
        self._add_messages(test_database, test_conversation.id, 20)

        response = client.get(
            f"/api/conversations/{test_conversation.id}/compaction",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["active"] is False
        assert data["summarized_count"] == 0
        assert data["total_count"] == 20
        assert data["boundary_message_id"] is None
        assert data["summary"] is None

    def test_returns_404_for_nonexistent_conversation(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/api/conversations/nonexistent-id/compaction", headers=auth_headers)
        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient, test_conversation: Conversation) -> None:
        response = client.get(f"/api/conversations/{test_conversation.id}/compaction")
        assert response.status_code == 401
