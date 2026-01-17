import json
import sys
import uuid
from pathlib import Path

from apiflask import APIFlask
from flask import Response, render_template, request, send_from_directory

from src.api.rate_limiting import init_rate_limiting
from src.api.routes import register_blueprints
from src.config import Config
from src.utils.logging import get_logger, set_request_id, setup_logging


def create_app() -> APIFlask:
    """Create and configure the Flask application."""
    # Setup structured logging first
    setup_logging()
    logger = get_logger(__name__)
    logger.info(
        "Flask app created",
        extra={
            "environment": Config.FLASK_ENV,
            "log_level": Config.LOG_LEVEL,
        },
    )

    app = APIFlask(
        __name__,
        static_folder="../static",
        static_url_path="/static",
        template_folder="templates",
        title="AI Chatbot API",
        version="1.0.0",
        spec_path="/api/openapi.json",
        docs_path="/api/docs",
        docs_ui="swagger-ui",  # Use 'redoc' for ReDoc
    )
    # Note: APIFlask's @api.output() decorator auto-serializes responses.
    # Error responses are returned as Flask Response objects to bypass this serialization.
    # See errors.py for details.

    # Set max request size to prevent DoS attacks
    app.config["MAX_CONTENT_LENGTH"] = Config.MAX_REQUEST_SIZE

    # Request ID middleware - must be before blueprints
    @app.before_request
    def add_request_id() -> None:
        """Generate and store request ID for correlation."""
        from flask import g

        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        set_request_id(request_id)
        g.request_id = request_id

    # Log all requests
    @app.before_request
    def log_request() -> None:
        """Log incoming requests."""
        logger.info(
            "Incoming request",
            extra={
                "method": request.method,
                "path": request.path,
                "remote_addr": request.remote_addr,
                "user_agent": request.headers.get("User-Agent", ""),
            },
        )

    # Log responses
    @app.after_request
    def log_response(response: Response) -> Response:
        """Log outgoing responses."""
        logger.info(
            "Outgoing response",
            extra={
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "content_length": response.content_length,
            },
        )
        return response

    # Initialize rate limiting before registering blueprints
    # This ensures the limiter is available when routes are registered
    init_rate_limiting(app)

    # Register all blueprints from routes module
    register_blueprints(app)

    # Custom error processor to return our standardized error format
    # APIFlask calls this for all HTTPError exceptions (including APIError)
    @app.error_processor
    def custom_error_processor(error):  # type: ignore[no-untyped-def]
        """Process errors and return our custom error format.

        For APIError (our custom class), the error data is in extra_data.
        For standard HTTPError, we wrap the message in our format.
        """
        from src.api.errors import APIError, ErrorCode, is_retryable

        if isinstance(error, APIError):
            # Our custom error - extra_data already has the correct format
            return error.extra_data, error.status_code, error.headers or {}

        # Standard HTTPError - wrap in our format
        # Map status codes to appropriate error codes
        status_to_code = {
            400: ErrorCode.VALIDATION_ERROR,
            401: ErrorCode.AUTH_REQUIRED,
            403: ErrorCode.AUTH_FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
            413: ErrorCode.PAYLOAD_TOO_LARGE,
            429: ErrorCode.RATE_LIMITED,
            500: ErrorCode.SERVER_ERROR,
            502: ErrorCode.EXTERNAL_SERVICE_ERROR,
            503: ErrorCode.SERVICE_UNAVAILABLE,
            504: ErrorCode.TIMEOUT,
        }
        code = status_to_code.get(error.status_code, ErrorCode.SERVER_ERROR)

        return (
            {
                "error": {
                    "code": code.value,
                    "message": error.message or "An error occurred",
                    "retryable": is_retryable(code),
                }
            },
            error.status_code,
            error.headers or {},
        )

    # Load Vite manifest for production builds
    vite_manifest: dict[str, dict[str, str | list[str]]] = {}
    manifest_path = Path(app.static_folder or "static") / "assets" / ".vite" / "manifest.json"
    if manifest_path.exists():
        try:
            with open(manifest_path) as f:
                vite_manifest = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(
                "Failed to load Vite manifest",
                extra={"path": str(manifest_path), "error": str(e)},
            )

    # Extract app version from manifest (JS bundle hash)
    app_version: str | None = None
    if vite_manifest:
        main_entry = vite_manifest.get("src/main.ts", {})
        js_file = str(main_entry.get("file", ""))
        # Extract hash: "assets/main-y-VVsbiY.js" -> "y-VVsbiY"
        if "-" in js_file and js_file.endswith(".js"):
            app_version = js_file.rsplit("-", 1)[1].replace(".js", "")

    # Store version in app config for access by routes
    app.config["APP_VERSION"] = app_version

    @app.route("/")
    def index() -> str | tuple[str, int]:
        logger.debug("Rendering index page")
        js_file: str | None = None
        css_file: str | None = None

        # In development mode, always use Vite dev server (ignore manifest)
        dev_mode = Config.is_development()

        if not dev_mode:
            # Production: require manifest and use hashed filenames
            if not vite_manifest:
                logger.error("Vite manifest not found in production mode")
                return "Frontend not built. Run 'make build' first.", 500
            main_entry = vite_manifest.get("src/main.ts", {})
            js_file = str(main_entry.get("file")) if main_entry.get("file") else None
            css_files = main_entry.get("css", [])
            if isinstance(css_files, list) and css_files:
                css_file = str(css_files[0])
            logger.debug(
                "Loaded production assets",
                extra={"js_file": js_file, "css_file": css_file, "app_version": app_version},
            )

        return render_template(
            "index.html",
            js_file=js_file,
            css_file=css_file,
            dev_mode=dev_mode,
            app_version=app_version,
        )

    # Serve static files
    @app.route("/<path:path>")
    def static_files(path: str) -> Response:
        return send_from_directory(app.static_folder or "static", path)

    # Start dev scheduler in development mode
    if Config.is_development():
        from src.agent.dev_scheduler import start_dev_scheduler

        start_dev_scheduler()

    return app


def main() -> None:
    """Main entry point."""
    # Setup logging early
    setup_logging()
    logger = get_logger(__name__)

    # Validate configuration
    errors = Config.validate()
    if errors:
        logger.error("Configuration validation failed", extra={"errors": errors})
        print("Configuration errors:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)

    # Check database connectivity before starting app
    from src.db.models import check_database_connectivity

    db_ok, db_error = check_database_connectivity()
    if not db_ok:
        logger.error("Database connectivity check failed", extra={"error": db_error})
        print(f"Database error: {db_error}")
        sys.exit(1)

    logger.info("Database connectivity verified", extra={"db_path": str(Config.DATABASE_PATH)})

    app = create_app()
    logger.info(
        "Starting AI Chatbot",
        extra={
            "port": Config.PORT,
            "environment": Config.FLASK_ENV,
            "models": list(Config.MODELS.keys()),
            "log_level": Config.LOG_LEVEL,
        },
    )
    app.run(host="0.0.0.0", port=Config.PORT, debug=Config.is_development())


if __name__ == "__main__":
    main()
