"""Device check runner routes (admin only): runs and the fixture conversation.

Attached to admin.api (one "Admin" OpenAPI tag).
"""

from typing import Any

from src.api.helpers.device_checks import create_fixture, save_run
from src.api.routes.admin import api
from src.api.schemas.device_checks import (
    DeviceCheckFixtureResponse,
    DeviceCheckRun,
    DeviceCheckRunRequest,
    DeviceCheckRunsQuery,
    DeviceCheckRunsResponse,
)
from src.api.validation import validate_query, validate_request
from src.auth.admin import require_admin
from src.auth.jwt_auth import require_auth
from src.db.models import User, db


@api.route("/admin/device-check-runs", methods=["POST"])
@api.output(DeviceCheckRun, status_code=201)
@api.doc(responses=[400, 401, 403])
@require_auth
@require_admin
@validate_request(DeviceCheckRunRequest)
def create_device_check_run(user: User, data: DeviceCheckRunRequest) -> dict[str, Any]:
    """Store a finished device check run."""
    return save_run(user.id, data)


@api.route("/admin/device-check-runs", methods=["GET"])
@api.output(DeviceCheckRunsResponse)
@api.doc(responses=[401, 403])
@require_auth
@require_admin
@validate_query(DeviceCheckRunsQuery)
def list_device_check_runs(user: User, query: DeviceCheckRunsQuery) -> dict[str, Any]:
    """Device check runs, newest first."""
    return {"runs": db.list_device_check_runs(query.limit)}


@api.route("/admin/device-check-fixture", methods=["POST"])
@api.output(DeviceCheckFixtureResponse, status_code=201)
@api.doc(responses=[401, 403])
@require_auth
@require_admin
def create_device_check_fixture(user: User) -> dict[str, Any]:
    """A fresh archived fixture conversation (any left by a crashed run is purged)."""
    return create_fixture(user.id)


@api.route("/admin/device-check-fixture", methods=["DELETE"])
@api.doc(responses=[204, 401, 403])
@require_auth
@require_admin
def delete_device_check_fixture(user: User) -> tuple[str, int]:
    """Permanently delete the user's fixture conversations."""
    db.purge_device_check_fixtures(user.id)
    return "", 204
