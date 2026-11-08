"""Jobs: the one list of everything that runs on a schedule - items set from
chats and standing jobs (agents). Standing chats phase 3."""

from __future__ import annotations

from apiflask import APIBlueprint

from src.api.helpers.job_responses import jobs_overview
from src.api.schemas.jobs import JobsOverviewResponse
from src.auth.jwt_auth import require_auth
from src.db.models import User

api = APIBlueprint("jobs", __name__, url_prefix="/api", tag="Jobs")


@api.route("/jobs", methods=["GET"])
@api.output(JobsOverviewResponse)
@api.doc(responses=[401])
@require_auth
def get_jobs(user: User) -> dict[str, object]:
    """Every job, needs attention first: each with its recent runs and next run."""
    return jobs_overview(user.id)
