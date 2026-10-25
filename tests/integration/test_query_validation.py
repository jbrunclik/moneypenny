"""@validate_query: query strings validated by a schema (rule B4).

The decorator injects the validated model like @validate_request injects the
body, answers a bad value with the standard 400, and documents the
parameters in the OpenAPI spec. The route tests pin each converted handler's
reading of its parameters: defaults, clamping, and the lenient fallbacks the
routes always had.
"""

from collections.abc import Callable
from functools import wraps
from typing import Any

import pytest
from apiflask import APIFlask
from flask import Flask
from flask.testing import FlaskClient

import src.api.routes.chat as chat_routes
import src.api.routes.planner as planner_routes
from src.api.schemas.base import QueryModel
from src.api.validation import validate_query
from src.db.models import Database, User
from src.enums import PaginationDirection


def _spy(monkeypatch: pytest.MonkeyPatch, owner: Any, name: str) -> list[dict[str, Any]]:
    """Record each call's arguments, then run the real function."""
    calls: list[dict[str, Any]] = []
    original = getattr(owner, name)

    def recorder(*args: Any, **kwargs: Any) -> Any:
        calls.append({"args": args, **kwargs})
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, name, recorder)
    return calls


def _field(response: Any) -> str | None:
    return response.get_json()["error"].get("details", {}).get("field")  # type: ignore[no-any-return]


# --- The decorator ---------------------------------------------------------


class _ItemQuery(QueryModel):
    page: int = 1
    tag: str | None = None


def _inject_user(f: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return f("the-user", *args, **kwargs)

    return wrapper


@pytest.fixture
def item_client() -> FlaskClient:
    app = APIFlask(__name__)

    @app.get("/items/<item_id>")
    @_inject_user
    @validate_query(_ItemQuery)
    def get_item(user: str, query: _ItemQuery, item_id: str) -> dict[str, Any]:
        return {"user": user, "page": query.page, "tag": query.tag, "item_id": item_id}

    return app.test_client()


class TestValidateQuery:
    def test_injects_the_model_after_injected_args_and_before_url_args(
        self, item_client: FlaskClient
    ) -> None:
        response = item_client.get("/items/i1?page=3&tag=a&tag=b&extra=ignored")
        assert response.status_code == 200
        # A repeated parameter reads its first value, as request.args.get() did
        assert response.get_json() == {"user": "the-user", "page": 3, "tag": "a", "item_id": "i1"}

    def test_defaults_apply_when_parameters_are_missing(self, item_client: FlaskClient) -> None:
        assert item_client.get("/items/i1").get_json()["page"] == 1

    def test_invalid_value_is_a_400_naming_the_field(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        # Through the real app, so the error has the API's standard shape
        response = client.get("/api/users/me/costs/monthly?year=10000", headers=auth_headers)
        assert response.status_code == 400
        error = response.get_json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert error["details"]["field"] == "year"

    def test_the_spec_documents_the_parameters(self, app: Flask) -> None:
        params = app.spec["paths"]["/api/conversations/{conv_id}/messages"]["get"]["parameters"]  # type: ignore[attr-defined]
        query = {p["name"] for p in params if p["in"] == "query"}
        assert query == {"limit", "cursor", "direction", "around_message_id"}
        assert {p["name"] for p in params if p["in"] == "path"} == {"conv_id"}

    def test_every_validated_route_documents_its_query(self, app: Flask) -> None:
        missing = []
        for rule in app.url_map.iter_rules():
            view = app.view_functions[rule.endpoint]
            schema = getattr(view, "_validated_query", None)
            if schema is None:
                continue
            path = "/".join(
                "{" + part[1:-1].split(":")[-1] + "}" if part.startswith("<") else part
                for part in rule.rule.split("/")
            )
            for method in rule.methods - {"HEAD", "OPTIONS"}:  # type: ignore[operator]
                operation = app.spec["paths"].get(path, {}).get(method.lower(), {})  # type: ignore[attr-defined]
                documented = {p["name"] for p in operation.get("parameters", [])}
                if not set(schema.model_fields) <= documented:
                    missing.append(f"{method} {rule.rule}")
        assert not missing, missing


# --- Conversation lists ----------------------------------------------------


@pytest.mark.parametrize(
    ("url", "method"),
    [
        ("/api/conversations", "list_conversations_paginated_with_counts"),
        ("/api/conversations/archived", "list_archived_conversations_paginated"),
        ("/api/conversations/trash", "list_trashed_conversations_paginated"),
    ],
)
@pytest.mark.parametrize(
    ("query", "limit", "cursor"),
    [
        ("", 30, None),  # defaults
        ("limit=9999", 100, None),  # clamped to the max page size
        ("limit=0", 1, None),
        ("limit=-5", 1, None),
        ("limit=abc", 30, None),  # unparsable -> default
        ("limit=", 30, None),
        ("limit=7&cursor=t:c1", 7, "t:c1"),
    ],
)
def test_conversation_list_paging(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    method: str,
    query: str,
    limit: int,
    cursor: str | None,
) -> None:
    calls = _spy(monkeypatch, test_database, method)
    response = client.get(f"{url}?{query}", headers=auth_headers)
    assert response.status_code == 200
    assert (calls[0]["limit"], calls[0]["cursor"]) == (limit, cursor)


# --- Messages --------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "limit", "cursor", "direction"),
    [
        ("", 50, None, PaginationDirection.OLDER),
        ("limit=1000&direction=newer&cursor=t:c1", 200, "t:c1", PaginationDirection.NEWER),
        ("limit=0&direction=sideways", 1, None, PaginationDirection.OLDER),
        ("limit=abc&direction=", 50, None, PaginationDirection.OLDER),
        ("around_message_id=", 50, None, PaginationDirection.OLDER),  # blank: plain paging
    ],
)
def test_messages_paging(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_conversation: Any,
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    limit: int,
    cursor: str | None,
    direction: PaginationDirection,
) -> None:
    calls = _spy(monkeypatch, test_database, "get_messages_paginated")
    response = client.get(
        f"/api/conversations/{test_conversation.id}/messages?{query}", headers=auth_headers
    )
    assert response.status_code == 200
    call = calls[0]
    assert (call["limit"], call["cursor"], call["direction"]) == (limit, cursor, direction)


@pytest.mark.parametrize(
    ("query", "limit", "cursor", "direction"),
    [
        ("", 50, None, PaginationDirection.OLDER),
        (
            "message_limit=500&message_cursor=t:c1&direction=newer",
            200,
            "t:c1",
            PaginationDirection.NEWER,
        ),
        ("message_limit=x&direction=bogus", 50, None, PaginationDirection.OLDER),
    ],
)
def test_conversation_detail_paging(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_conversation: Any,
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    limit: int,
    cursor: str | None,
    direction: PaginationDirection,
) -> None:
    calls = _spy(monkeypatch, test_database, "get_messages_paginated")
    response = client.get(
        f"/api/conversations/{test_conversation.id}?{query}", headers=auth_headers
    )
    assert response.status_code == 200
    call = calls[0]
    assert (call["limit"], call["cursor"], call["direction"]) == (limit, cursor, direction)


@pytest.mark.parametrize(
    ("path", "query", "field"),
    [
        ("/api/conversations", "cursor=abc", "cursor"),
        ("/api/conversations/archived", "cursor=abc", "cursor"),
        ("/api/conversations/trash", "cursor=abc", "cursor"),
        ("/api/conversations/{id}/messages", "cursor=abc", "cursor"),
        ("/api/conversations/{id}", "message_cursor=abc", "message_cursor"),
    ],
)
def test_malformed_page_cursor_is_a_400(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Any,
    path: str,
    query: str,
    field: str,
) -> None:
    """A cursor without its ':' separator was a 500 (ValueError in parse_cursor)."""
    url = path.format(id=test_conversation.id)
    response = client.get(f"{url}?{query}", headers=auth_headers)
    assert response.status_code == 400
    assert _field(response) == field


# --- Sync ------------------------------------------------------------------


class TestSyncQuery:
    def test_full_is_case_insensitive(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get(
            "/api/conversations/sync?since=2099-01-01T00:00:00&full=TRUE", headers=auth_headers
        )
        assert response.get_json()["is_full_sync"] is True

    def test_anything_but_true_is_not_full(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get(
            "/api/conversations/sync?since=2099-01-01T00:00:00&full=1", headers=auth_headers
        )
        assert response.status_code == 200
        assert response.get_json()["is_full_sync"] is False

    def test_full_ignores_a_bad_cursor(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/api/conversations/sync?cursor=abc&full=true", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json()["is_full_sync"] is True

    def test_blank_cursor_is_rejected(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/api/conversations/sync?cursor=", headers=auth_headers)
        assert response.status_code == 400
        assert _field(response) == "cursor"


# --- Search ----------------------------------------------------------------


class TestSearchQuery:
    @pytest.mark.parametrize(
        ("query", "limit", "offset"),
        [
            ("", 20, 0),
            ("&limit=100&offset=-3", 50, 0),  # clamped
            ("&limit=0", 1, 0),
            ("&limit=abc&offset=xyz", 20, 0),  # unparsable -> default
            ("&limit=5&offset=10", 5, 10),
        ],
    )
    def test_paging(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        monkeypatch: pytest.MonkeyPatch,
        query: str,
        limit: int,
        offset: int,
    ) -> None:
        calls = _spy(monkeypatch, test_database, "search")
        response = client.get(f"/api/search?q=+python+{query}", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json()["query"] == "python"  # stripped
        assert (calls[0]["limit"], calls[0]["offset"]) == (limit, offset)

    @pytest.mark.parametrize(
        ("query", "message"),
        [
            ("", "Search query is required"),
            ("q=+++", "Search query is required"),
            ("q=" + "x" * 201, "Search query too long (max 200 characters)"),
        ],
    )
    def test_bad_query_text(
        self, client: FlaskClient, auth_headers: dict[str, str], query: str, message: str
    ) -> None:
        response = client.get(f"/api/search?{query}", headers=auth_headers)
        assert response.status_code == 400
        assert response.get_json()["error"]["message"] == message
        assert _field(response) == "q"


# --- Planner ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "force_refresh"),
    [
        ("", False),
        ("force_refresh=true", True),
        ("force_refresh=True", True),
        ("force_refresh=1", False),
    ],
)
def test_planner_force_refresh(
    client: FlaskClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    force_refresh: bool,
) -> None:
    calls = _spy(monkeypatch, planner_routes, "build_planner_dashboard")
    response = client.get(f"/api/planner?{query}", headers=auth_headers)
    assert response.status_code == 200
    assert calls[0]["force_refresh"] is force_refresh


# --- Stream resume ---------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "after_seq"), [("", 0), ("after_seq=7", 7), ("after_seq=abc", 0)]
)
def test_resume_after_seq(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_conversation: Any,
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    after_seq: int,
) -> None:
    calls: list[tuple[str, int]] = []

    def fake_resume(message_id: str, seq: int) -> Any:
        calls.append((message_id, seq))
        return iter(())

    monkeypatch.setattr(chat_routes, "stream_resume_events", fake_resume)
    message = test_database.add_message(test_conversation.id, "assistant", "Hi")
    response = client.get(
        f"/api/conversations/{test_conversation.id}/chat/stream/{message.id}/resume?{query}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    response.get_data()  # drain the stream
    assert calls == [(message.id, after_seq)]


# --- Costs -----------------------------------------------------------------


class TestCostQueries:
    def test_monthly_defaults_to_this_month(
        self, client: FlaskClient, auth_headers: dict[str, str], test_user: User
    ) -> None:
        from datetime import datetime

        now = datetime.now()
        for query in ("", "year=abc&month=", "year=0&month=0"):
            data = client.get(
                f"/api/users/me/costs/monthly?{query}", headers=auth_headers
            ).get_json()
            assert (data["year"], data["month"]) == (now.year, now.month), query

    @pytest.mark.parametrize(
        ("query", "field"),
        [("month=13", "month"), ("year=10000", "year"), ("year=-1", "year")],
    )
    def test_monthly_rejects_out_of_range(
        self, client: FlaskClient, auth_headers: dict[str, str], query: str, field: str
    ) -> None:
        response = client.get(f"/api/users/me/costs/monthly?{query}", headers=auth_headers)
        assert response.status_code == 400
        assert _field(response) == field

    @pytest.mark.parametrize(
        ("query", "limit"),
        [("", 12), ("limit=0", 12), ("limit=abc", 12), ("limit=999", 120), ("limit=3", 3)],
    )
    def test_history_limit(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        monkeypatch: pytest.MonkeyPatch,
        query: str,
        limit: int,
    ) -> None:
        calls = _spy(monkeypatch, test_database, "get_user_cost_history")
        response = client.get(f"/api/users/me/costs/history?{query}", headers=auth_headers)
        assert response.status_code == 200
        assert calls[0]["args"][1] == limit

    def test_history_rejects_a_negative_limit(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/api/users/me/costs/history?limit=-1", headers=auth_headers)
        assert response.status_code == 400
        assert _field(response) == "limit"
