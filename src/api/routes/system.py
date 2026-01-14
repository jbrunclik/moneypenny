"""System routes: models, config, version, and health checks.

This module contains utility routes for system information and health monitoring.
"""

from typing import Any

from apiflask import APIBlueprint
from flask import current_app

from src.api.rate_limiting import exempt_from_rate_limit
from src.api.schemas import (
    HealthResponse,
    ModelsListResponse,
    ReadinessResponse,
    UploadConfigResponse,
    VersionResponse,
)
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User, check_database_connectivity
from src.utils.logging import get_logger

logger = get_logger(__name__)

api = APIBlueprint("system", __name__, url_prefix="/api", tag="System")


# ============================================================================
# Models Routes
# ============================================================================


@api.route("/models", methods=["GET"])
@api.output(ModelsListResponse)
@require_auth
def list_models(user: User) -> dict[str, Any]:
    """List available models."""
    # user parameter required by @require_auth but not used in this endpoint
    _ = user
    return {
        "models": [
            {"id": model_id, "name": model_info["name"], "short_name": model_info["short_name"]}
            for model_id, model_info in Config.MODELS.items()
        ],
        "default": Config.DEFAULT_MODEL,
    }


# ============================================================================
# Config Routes
# ============================================================================


@api.route("/config/upload", methods=["GET"])
@api.output(UploadConfigResponse)
@require_auth
def get_upload_config(user: User) -> dict[str, Any]:
    """Get file upload configuration for frontend."""
    # user parameter required by @require_auth but not used in this endpoint
    _ = user
    return {
        "maxFileSize": Config.MAX_FILE_SIZE,
        "maxFilesPerMessage": Config.MAX_FILES_PER_MESSAGE,
        "allowedFileTypes": list(Config.ALLOWED_FILE_TYPES),
    }


# ============================================================================
# Version Routes
# ============================================================================


@api.route("/version", methods=["GET"])
@api.output(VersionResponse)
@exempt_from_rate_limit
def get_version() -> dict[str, str | None]:
    """Get current app version (JS bundle hash).

    This endpoint does not require authentication so version can be
    checked even before login. Used by frontend to detect when a new
    version is deployed and prompt users to reload.
    """
    return {"version": current_app.config.get("APP_VERSION")}


# ============================================================================
# Health Check Routes
# ============================================================================


@api.route("/health", methods=["GET"])
@api.output(HealthResponse)
@exempt_from_rate_limit
def health_check() -> tuple[dict[str, str | None], int]:
    """Liveness probe - checks if the application process is running.

    This endpoint should NOT check external dependencies (database, APIs).
    It only verifies the Flask application is responding to requests.

    Use /api/ready for readiness checks that verify dependencies.

    Returns:
        200: Application is alive and responding
    """
    return {
        "status": "ok",
        "version": current_app.config.get("APP_VERSION"),
    }, 200


@api.route("/ready", methods=["GET"])
@api.output(ReadinessResponse)
@api.doc(responses=[503])
@exempt_from_rate_limit
def readiness_check() -> tuple[dict[str, Any], int]:
    """Readiness probe - checks if the application can serve traffic.

    Verifies that all dependencies (database) are accessible.
    Use this for load balancer health checks that should remove
    unhealthy instances from the pool.

    Returns:
        200: Application is ready to serve traffic
        503: Application is not ready (dependency failure)
    """
    checks: dict[str, dict[str, Any]] = {}
    is_ready = True

    # Check database connectivity
    db_ok, db_error = check_database_connectivity()
    checks["database"] = {
        "status": "ok" if db_ok else "error",
        "message": "Connected" if db_ok else db_error,
    }
    if not db_ok:
        is_ready = False
        logger.error("Readiness check failed: database", extra={"error": db_error})

    response = {
        "status": "ready" if is_ready else "not_ready",
        "checks": checks,
        "version": current_app.config.get("APP_VERSION"),
    }

    status_code = 200 if is_ready else 503
    if is_ready:
        logger.debug("Readiness check passed")
    else:
        logger.warning("Readiness check failed", extra={"checks": checks})

    return response, status_code
