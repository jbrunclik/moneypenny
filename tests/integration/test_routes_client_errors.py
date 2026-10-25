"""Browser error reports (POST /api/client-errors) and the admin view of them.

Errors used to live only in each device's console. A report becomes one row
per user and fingerprint, so a recurring error counts up instead of piling up.
"""

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch

from flask.testing import FlaskClient

from src.auth.jwt_auth import create_token
from src.config import Config
from src.db.models import Database, User

URL = "/api/client-errors"
STACK = (
    "TypeError: x is undefined\n"
    "    at renderList (https://app.example/static/assets/main-DbvD3EMh.js:2:5185)\n"
    "    at init (https://app.example/static/assets/main-DbvD3EMh.js:9:12)"
)


def _report(**overrides: Any) -> dict[str, Any]:
    return {
        "kind": "error",
        "message": "x is undefined",
        "stack": STACK,
        "path": "/chat/abc",
        "app_version": "1.2.3",
        **overrides,
    }


def _rows(db: Database) -> list[dict[str, Any]]:
    return db.top_client_errors(datetime.now() - timedelta(days=1), limit=50)


class TestReport:
    def test_records_the_error(
        self, client: FlaskClient, auth_headers: dict[str, str], test_database: Database
    ) -> None:
        response = client.post(URL, json=_report(), headers=auth_headers)
        assert response.status_code == 204
        [row] = _rows(test_database)
        assert (row["kind"], row["message"], row["path"], row["count"], row["users"]) == (
            "error",
            "x is undefined",
            "/chat/abc",
            1,
            1,
        )
        assert "renderList" in row["stack"]

    def test_a_repeat_counts_up_on_one_row(
        self, client: FlaskClient, auth_headers: dict[str, str], test_database: Database
    ) -> None:
        client.post(URL, json=_report(), headers=auth_headers)
        # A new build changes the asset hash and line numbers, not the error
        later = STACK.replace("DbvD3EMh", "Xy12AbCd").replace("2:5185", "2:5190")
        client.post(URL, json=_report(stack=later), headers=auth_headers)
        [row] = _rows(test_database)
        assert row["count"] == 2

    def test_two_users_with_one_error_show_as_one_entry(
        self, client: FlaskClient, auth_headers: dict[str, str], test_database: Database
    ) -> None:
        other = test_database.get_or_create_user(email="other@example.com", name="Other")
        client.post(URL, json=_report(), headers=auth_headers)
        client.post(URL, json=_report(), headers={"Authorization": f"Bearer {create_token(other)}"})
        [row] = _rows(test_database)
        assert (row["count"], row["users"]) == (2, 2)

    def test_long_text_is_cut_and_the_query_dropped(
        self, client: FlaskClient, auth_headers: dict[str, str], test_database: Database
    ) -> None:
        client.post(
            URL,
            json=_report(message="m" * 1500, stack="s" * 7000, path="/chat/abc?q=private"),
            headers=auth_headers,
        )
        [row] = _rows(test_database)
        assert len(row["message"]) <= 300
        assert len(row["stack"]) <= 2000
        assert row["path"] == "/chat/abc"

    def test_requires_a_token(self, client: FlaskClient) -> None:
        assert client.post(URL, json=_report()).status_code == 401

    def test_rejects_an_unknown_kind(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        assert client.post(URL, json=_report(kind="panic"), headers=auth_headers).status_code == 400


class TestRetention:
    def test_rows_unseen_past_retention_are_pruned(
        self, test_database: Database, test_user: User
    ) -> None:
        old = datetime.now() - timedelta(days=Config.CLIENT_ERROR_RETENTION_DAYS + 1)
        test_database.record_client_error(
            test_user.id, "fp-old", "error", "old", None, None, None, None, now=old
        )
        test_database.record_client_error(
            test_user.id, "fp-new", "error", "new", None, None, None, None
        )
        messages = [
            r["message"] for r in test_database.top_client_errors(old - timedelta(days=1), 50)
        ]
        assert messages == ["new"]

    def test_each_user_keeps_at_most_the_cap(
        self, test_database: Database, test_user: User
    ) -> None:
        start = datetime.now() - timedelta(hours=1)
        with patch.object(Config, "CLIENT_ERROR_MAX_ROWS_PER_USER", 3):
            for i in range(5):
                test_database.record_client_error(
                    test_user.id,
                    f"fp-{i}",
                    "error",
                    f"e{i}",
                    None,
                    None,
                    None,
                    None,
                    now=start + timedelta(minutes=i),
                )
        messages = {
            r["message"] for r in test_database.top_client_errors(start - timedelta(days=1), 50)
        }
        assert messages == {"e2", "e3", "e4"}  # the most recently seen survive


class TestAdminOverview:
    def test_lists_recent_browser_errors_most_frequent_first(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
    ) -> None:
        client.post(URL, json=_report(message="rare"), headers=auth_headers)
        for _ in range(3):
            client.post(URL, json=_report(message="common"), headers=auth_headers)
        with patch.object(Config, "ADMIN_EMAILS", [test_user.email]):
            data = client.get("/api/admin/overview", headers=auth_headers).get_json()
        errors = data["browser_errors"]
        assert [(e["message"], e["count"]) for e in errors] == [("common", 3), ("rare", 1)]
