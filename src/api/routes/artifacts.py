"""Artifact routes: a version's HTML for the sandboxed frame, and saved state.

The frame itself (/artifact-frame, src/app.py) never fetches anything: the chat
fetches here with the user's token and posts the HTML into the frame.
"""

from __future__ import annotations

import json
from typing import Any

from apiflask import APIBlueprint

from src.api.errors import raise_not_found_error, raise_payload_too_large_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.schemas.artifacts import ArtifactStateRequest, ArtifactVersionResponse
from src.api.schemas.common import StatusResponse
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)

api = APIBlueprint("artifacts", __name__, url_prefix="/api/artifacts", tag="Artifacts")


@api.route("/<artifact_id>/versions/<int:version>", methods=["GET"])
@api.output(ArtifactVersionResponse)
@api.doc(responses=[401, 404])
@require_auth
def get_artifact_version(user: User, artifact_id: str, version: int) -> dict[str, Any]:
    """One version's HTML plus the artifact's saved state."""
    art = db.get_artifact_for_user(artifact_id, user.id)
    found = db.get_artifact_version(artifact_id, version) if art else None
    if art is None or found is None:
        raise_not_found_error("Artifact")
    return {
        "id": art.id,
        "version": found.version,
        "title": art.title,
        "html": found.html,
        "state": art.state,
    }


@api.route("/<artifact_id>/state", methods=["PUT"])
@api.output(StatusResponse)
@api.doc(responses=[400, 401, 404, 413])
@rate_limit_conversations
@require_auth
@validate_request(ArtifactStateRequest)
def put_artifact_state(
    user: User, data: ArtifactStateRequest, artifact_id: str
) -> tuple[dict[str, str], int]:
    """Replace the state an artifact saved (ticked items, scores)."""
    if db.get_artifact_for_user(artifact_id, user.id) is None:
        raise_not_found_error("Artifact")
    size = len(json.dumps(data.state).encode("utf-8")) if data.state is not None else 0
    if size > Config.ARTIFACT_STATE_MAX_BYTES:
        raise_payload_too_large_error(Config.ARTIFACT_STATE_MAX_BYTES)
    db.set_artifact_state(artifact_id, data.state)
    return {"status": "saved"}, 200
