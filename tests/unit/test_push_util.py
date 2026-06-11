"""Unit tests for the Web Push send pipeline (src/utils/push.py)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from pywebpush import WebPushException

from src.config import Config
from src.utils.push import send_push_to_user, send_push_to_user_sync

if TYPE_CHECKING:
    from src.db.models import Database, User


def _webpush_error(status: int) -> WebPushException:
    response = MagicMock()
    response.status_code = status
    return WebPushException("push failed", response=response)


@pytest.fixture
def push_user(test_database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch) -> User:
    """A user with one stored subscription and the module db patched."""
    monkeypatch.setattr("src.db.models.db", test_database)
    test_database.save_push_subscription(
        user_id=test_user.id,
        endpoint="https://push.example.com/sub-1",
        p256dh="p256dh-key",
        auth="auth-secret",
        user_agent="pytest",
    )
    return test_user


class TestSendPushToUserSync:
    def test_delivers_to_all_subscriptions(self, push_user: User, test_database: Database) -> None:
        test_database.save_push_subscription(
            user_id=push_user.id,
            endpoint="https://push.example.com/sub-2",
            p256dh="k2",
            auth="a2",
        )
        with patch("src.utils.push.webpush") as mock_webpush:
            delivered = send_push_to_user_sync(push_user.id, "Title", "Body", "/", "tag-1")

        assert delivered == 2
        assert mock_webpush.call_count == 2
        payload = mock_webpush.call_args.kwargs["data"]
        assert '"title": "Title"' in payload
        assert '"tag": "tag-1"' in payload
        # Successful send stamps last_used_at
        subs = test_database.get_push_subscriptions(push_user.id)
        assert all(s.last_used_at is not None for s in subs)

    def test_no_subscriptions_returns_zero(
        self, test_database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.db.models.db", test_database)
        with patch("src.utils.push.webpush") as mock_webpush:
            assert send_push_to_user_sync(test_user.id, "T", "B", None, None) == 0
        mock_webpush.assert_not_called()

    @pytest.mark.parametrize("status", [404, 410])
    def test_gone_subscription_is_pruned(
        self, push_user: User, test_database: Database, status: int
    ) -> None:
        with patch("src.utils.push.webpush", side_effect=_webpush_error(status)):
            delivered = send_push_to_user_sync(push_user.id, "T", "B", None, None)

        assert delivered == 0
        assert test_database.get_push_subscriptions(push_user.id) == []

    def test_transient_failure_keeps_subscription(
        self, push_user: User, test_database: Database
    ) -> None:
        with patch("src.utils.push.webpush", side_effect=_webpush_error(500)):
            delivered = send_push_to_user_sync(push_user.id, "T", "B", None, None)

        assert delivered == 0
        assert len(test_database.get_push_subscriptions(push_user.id)) == 1

    def test_one_bad_subscription_does_not_block_others(
        self, push_user: User, test_database: Database
    ) -> None:
        test_database.save_push_subscription(
            user_id=push_user.id,
            endpoint="https://push.example.com/sub-2",
            p256dh="k2",
            auth="a2",
        )
        with patch(
            "src.utils.push.webpush", side_effect=[_webpush_error(410), None]
        ) as mock_webpush:
            delivered = send_push_to_user_sync(push_user.id, "T", "B", None, None)

        assert delivered == 1
        assert mock_webpush.call_count == 2
        assert len(test_database.get_push_subscriptions(push_user.id)) == 1


class TestSendPushToUser:
    def test_noop_when_push_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Config, "VAPID_PRIVATE_KEY", "")
        monkeypatch.setattr(Config, "VAPID_PUBLIC_KEY", "")
        with patch("src.utils.push.threading.Thread") as mock_thread:
            send_push_to_user("user-1", "T", "B")
        mock_thread.assert_not_called()

    def test_spawns_daemon_thread_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Config, "VAPID_PRIVATE_KEY", "priv")
        monkeypatch.setattr(Config, "VAPID_PUBLIC_KEY", "pub")
        with patch("src.utils.push.threading.Thread") as mock_thread:
            send_push_to_user("user-1", "T", "B", url="/x", tag="t")

        mock_thread.assert_called_once()
        kwargs = mock_thread.call_args.kwargs
        assert kwargs["daemon"] is True
        assert kwargs["args"] == ("user-1", "T", "B", "/x", "t")
        mock_thread.return_value.start.assert_called_once()


class TestPushSubscriptionMixin:
    def test_upsert_by_endpoint(self, test_database: Database, test_user: User) -> None:
        first = test_database.save_push_subscription(
            user_id=test_user.id, endpoint="https://e/1", p256dh="k1", auth="a1"
        )
        second = test_database.save_push_subscription(
            user_id=test_user.id, endpoint="https://e/1", p256dh="k2", auth="a2"
        )
        assert second.id == first.id
        subs = test_database.get_push_subscriptions(test_user.id)
        assert len(subs) == 1
        assert subs[0].p256dh == "k2"

    def test_delete_scoped_to_user(self, test_database: Database, test_user: User) -> None:
        other = test_database.get_or_create_user(email="other@example.com", name="Other")
        test_database.save_push_subscription(
            user_id=test_user.id, endpoint="https://e/1", p256dh="k", auth="a"
        )
        # Another user cannot delete someone else's subscription
        assert test_database.delete_push_subscription("https://e/1", user_id=other.id) is False
        assert test_database.delete_push_subscription("https://e/1", user_id=test_user.id) is True
