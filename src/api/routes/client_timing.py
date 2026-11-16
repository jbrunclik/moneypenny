"""Startup timing reports (POST /api/client-timing)."""

from apiflask import APIBlueprint

from src.api.schemas.client_timing import ClientTimingReport
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.db.models import User, db

api = APIBlueprint("client_timing", __name__, url_prefix="/api", tag="Client errors")


@api.route("/client-timing", methods=["POST"])
@api.doc(responses=[204, 400, 401])
@require_auth
@validate_request(ClientTimingReport)
def report_client_timing(user: User, data: ClientTimingReport) -> tuple[str, int]:
    """Record how long this page load's startup stages took."""
    db.add_client_boot_timing(
        user.id,
        {
            "marks": data.marks.model_dump(),
            "standalone": data.standalone,
            "viewport": data.viewport,
            "connection": data.connection,
            "app_version": data.app_version,
            "route": data.route,
        },
    )
    return "", 204
