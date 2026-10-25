"""Admin page and spend status routes (S12)."""

from typing import Any

from apiflask import APIBlueprint

from src.api.helpers.admin_overview import build_overview, spend_status
from src.api.schemas.admin import AdminOverviewResponse, SpendStatusResponse
from src.auth.admin import require_admin
from src.auth.jwt_auth import require_auth
from src.db.models import User

api = APIBlueprint("admin", __name__, url_prefix="/api", tag="Admin")


@api.route("/admin/overview", methods=["GET"])
@api.output(AdminOverviewResponse)
@api.doc(responses=[401, 403])
@require_auth
@require_admin
def get_admin_overview(user: User) -> dict[str, Any]:
    """Spend, agent health, search quotas, response quality and system facts."""
    return build_overview()


@api.route("/users/me/spend-status", methods=["GET"])
@api.output(SpendStatusResponse)
@api.doc(responses=[401])
@require_auth
def get_spend_status(user: User) -> dict[str, Any]:
    """The signed-in user's spend today against the warning threshold."""
    return spend_status(user.id)
