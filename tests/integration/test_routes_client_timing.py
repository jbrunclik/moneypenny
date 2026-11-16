"""Startup timing reports (POST /api/client-timing).

Slow opening was unmeasured; each page load reports how long its stages took,
so a cached sidebar or lazy KaTeX can be decided from data (Nov 16 2026,
docs/superpowers/specs/2026-11-16-client-reliability-design.md).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask.testing import FlaskClient

from src.config import Config
from src.db.models import Database, User
from src.db.models.timestamps import to_db

URL = "/api/client-timing"


def _report(**overrides: Any) -> dict[str, Any]:
    marks = {
        "response_end_ms": 120,
        "dom_content_loaded_ms": 300,
        "script_ms": 310,
        "auth_ms": 650,
        "data_ms": 1200,
        "route_ms": 1400,
        "ready_ms": 1900,
    }
    return {
        "marks": marks,
        "standalone": True,
        "viewport": "mobile",
        "connection": "4g",
        "app_version": "1.2.3",
        "route": "conversation",
        **overrides,
    }


def _rows(db: Database) -> list[sqlite3.Row]:
    with db._pool.get_connection() as conn:
        return conn.execute("SELECT * FROM client_boot_timings").fetchall()


def test_a_report_is_stored(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
) -> None:
    response = client.post(URL, json=_report(), headers=auth_headers)
    assert response.status_code == 204
    [row] = _rows(test_database)
    assert row["user_id"] == test_user.id
    assert (row["ready_ms"], row["auth_ms"], row["script_ms"]) == (1900, 650, 310)
    assert (row["standalone"], row["viewport"], row["connection"]) == (1, "mobile", "4g")
    assert (row["app_version"], row["route"]) == ("1.2.3", "conversation")


def test_missing_marks_are_stored_as_null(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database
) -> None:
    report = _report()
    report["marks"] = {"ready_ms": 900, "route_ms": None}
    assert client.post(URL, json=report, headers=auth_headers).status_code == 204
    [row] = _rows(test_database)
    assert (row["ready_ms"], row["route_ms"], row["auth_ms"]) == (900, None, None)


def test_auth_is_required(client: FlaskClient, test_database: Database) -> None:
    assert client.post(URL, json=_report()).status_code == 401
    assert _rows(test_database) == []


@pytest.mark.parametrize(
    "bad",
    [
        {"marks": {"ready_ms": -5}},
        {"marks": {"ready_ms": 600_001}},
        {"marks": {"ready_ms": 10, "surprise_ms": 3}},
        {"viewport": "tablet"},
        {"connection": "x" * 17},
        {"app_version": "v" * 65},
        {"route": "r" * 25},
        {"extra": True},
    ],
)
def test_absurd_reports_are_refused(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, bad: dict[str, Any]
) -> None:
    report = _report()
    if "marks" in bad:
        report["marks"] = bad["marks"]
    else:
        report.update(bad)
    assert client.post(URL, json=report, headers=auth_headers).status_code == 400
    assert _rows(test_database) == []


def test_old_reports_are_pruned_on_insert(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database
) -> None:
    client.post(URL, json=_report(), headers=auth_headers)
    old = datetime.now(UTC) - timedelta(days=Config.CLIENT_BOOT_TIMINGS_RETENTION_DAYS + 1)
    with test_database._pool.get_connection() as conn:
        conn.execute(
            "UPDATE client_boot_timings SET created_at = ?",
            (to_db(old),),
        )
        conn.commit()
    client.post(URL, json=_report(route="home"), headers=auth_headers)
    assert [row["route"] for row in _rows(test_database)] == ["home"]
