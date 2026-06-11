"""Integration tests for Web Push routes."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from src.config import Config

if TYPE_CHECKING:
    from flask.testing import FlaskClient

    from src.db.models import Database, User


SUBSCRIPTION = {
    "endpoint": "https://push.example.com/sub-1",
    "keys": {"p256dh": "p256dh-key", "auth": "auth-secret"},
}


class TestVapidPublicKey:
    def test_disabled_without_keys(
        self, client: FlaskClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Config, "VAPID_PRIVATE_KEY", "")
        monkeypatch.setattr(Config, "VAPID_PUBLIC_KEY", "")
        response = client.get("/api/push/vapid-public-key", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json() == {"enabled": False, "public_key": None}

    def test_enabled_with_keys(
        self, client: FlaskClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Config, "VAPID_PRIVATE_KEY", "priv")
        monkeypatch.setattr(Config, "VAPID_PUBLIC_KEY", "pub-key")
        response = client.get("/api/push/vapid-public-key", headers=auth_headers)
        data = response.get_json()
        assert data == {"enabled": True, "public_key": "pub-key"}

    def test_requires_auth(self, client: FlaskClient) -> None:
        assert client.get("/api/push/vapid-public-key").status_code == 401


class TestSubscribe:
    def test_stores_subscription(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        response = client.post("/api/push/subscriptions", headers=auth_headers, json=SUBSCRIPTION)
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

        subs = test_database.get_push_subscriptions(test_user.id)
        assert len(subs) == 1
        assert subs[0].endpoint == SUBSCRIPTION["endpoint"]
        assert subs[0].id == data["subscription_id"]

    def test_resubscribe_upserts(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        client.post("/api/push/subscriptions", headers=auth_headers, json=SUBSCRIPTION)
        updated = {**SUBSCRIPTION, "keys": {"p256dh": "new-key", "auth": "new-auth"}}
        response = client.post("/api/push/subscriptions", headers=auth_headers, json=updated)
        assert response.status_code == 200

        subs = test_database.get_push_subscriptions(test_user.id)
        assert len(subs) == 1
        assert subs[0].p256dh == "new-key"

    def test_validates_payload(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        response = client.post(
            "/api/push/subscriptions", headers=auth_headers, json={"endpoint": ""}
        )
        assert response.status_code == 400

    def test_requires_auth(self, client: FlaskClient) -> None:
        assert client.post("/api/push/subscriptions", json=SUBSCRIPTION).status_code == 401


class TestUnsubscribe:
    def test_removes_subscription(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        client.post("/api/push/subscriptions", headers=auth_headers, json=SUBSCRIPTION)
        response = client.delete(
            "/api/push/subscriptions",
            headers=auth_headers,
            json={"endpoint": SUBSCRIPTION["endpoint"]},
        )
        assert response.status_code == 200
        assert test_database.get_push_subscriptions(test_user.id) == []


class TestSendTest:
    def test_no_subscriptions(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        response = client.post("/api/push/test", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json()["status"] == "no_subscriptions"

    def test_sends_to_subscribed_device(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        client.post("/api/push/subscriptions", headers=auth_headers, json=SUBSCRIPTION)
        with patch("src.utils.push.webpush") as mock_webpush:
            response = client.post("/api/push/test", headers=auth_headers)

        assert response.status_code == 200
        assert response.get_json()["status"] == "ok"
        mock_webpush.assert_called_once()
