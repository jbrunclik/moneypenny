"""Browser error reports (POST /api/client-errors)."""

from apiflask import APIBlueprint
from flask import request

from src.api.helpers.client_errors import record_report
from src.api.schemas.client_errors import ClientErrorReport
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.db.models import User

api = APIBlueprint("client_errors", __name__, url_prefix="/api", tag="Client errors")


@api.route("/client-errors", methods=["POST"])
@api.doc(responses=[204, 400, 401])
@require_auth
@validate_request(ClientErrorReport)
def report_client_error(user: User, data: ClientErrorReport) -> tuple[str, int]:
    """Record an error the browser caught, for the admin page and reviews."""
    record_report(user.id, data, request.headers.get("User-Agent"))
    return "", 204
