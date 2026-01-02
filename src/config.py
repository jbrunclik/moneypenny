import os
from pathlib import Path

from dotenv import load_dotenv

from src.constants import BYTES_PER_KB, BYTES_PER_MB, SECONDS_PER_DAY, SECONDS_PER_WEEK

load_dotenv()


class Config:
    # Base paths
    BASE_DIR = Path(__file__).parent.parent

    # Gemini API
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # Available models
    MODELS = {
        "gemini-3-flash-preview": "Gemini 3 Flash (Fast)",
        "gemini-3-pro-preview": "Gemini 3 Pro (Advanced)",
    }
    DEFAULT_MODEL = "gemini-3-flash-preview"

    # Image generation model
    IMAGE_GENERATION_MODEL = "gemini-3-pro-image-preview"
    MAX_IMAGE_PROMPT_LENGTH: int = int(os.getenv("MAX_IMAGE_PROMPT_LENGTH", "2000"))  # characters

    # Google Identity Services (GIS) - only Client ID needed
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")

    # JWT Authentication
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRATION_SECONDS = SECONDS_PER_WEEK  # 1 week

    # Email whitelist
    ALLOWED_EMAILS: list[str] = [
        email.strip() for email in os.getenv("ALLOWED_EMAILS", "").split(",") if email.strip()
    ]

    # Server
    PORT: int = int(os.getenv("PORT", "8000"))
    FLASK_ENV: str = os.getenv("FLASK_ENV", "development")
    GUNICORN_WORKERS: int = int(os.getenv("GUNICORN_WORKERS", "2"))
    GUNICORN_TIMEOUT: int = int(os.getenv("GUNICORN_TIMEOUT", "300"))  # 5 minutes default
    SSE_KEEPALIVE_INTERVAL: int = int(os.getenv("SSE_KEEPALIVE_INTERVAL", "15"))  # seconds

    # Request timeouts (generous defaults to accommodate image generation and complex tool chains)
    # Image generation alone can take 30-60s, complex queries with multiple tools need more time
    CHAT_TIMEOUT: int = int(os.getenv("CHAT_TIMEOUT", "300"))  # 5 minutes for full chat request
    TOOL_TIMEOUT: int = int(os.getenv("TOOL_TIMEOUT", "90"))  # 90 seconds per tool execution
    FETCH_URL_MAX_FILE_SIZE: int = int(
        os.getenv("FETCH_URL_MAX_FILE_SIZE", str(10 * BYTES_PER_MB))
    )  # 10MB default for fetched files (PDFs, images)
    GOOGLE_AUTH_TIMEOUT: int = int(
        os.getenv("GOOGLE_AUTH_TIMEOUT", "10")
    )  # 10 seconds for Google token verification

    # Streaming cleanup thread timeouts
    STREAM_CLEANUP_THREAD_TIMEOUT: int = int(
        os.getenv("STREAM_CLEANUP_THREAD_TIMEOUT", "600")
    )  # 10 minutes for stream thread to complete
    STREAM_CLEANUP_WAIT_DELAY: float = float(
        os.getenv("STREAM_CLEANUP_WAIT_DELAY", "1.0")
    )  # 1 second delay before checking if message was saved

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

    # Slow query logging (only active in development/debug mode)
    SLOW_QUERY_THRESHOLD_MS: int = int(os.getenv("SLOW_QUERY_THRESHOLD_MS", "100"))

    # User location (for contextual responses - units, locale, recommendations)
    # Format: "City, Country" (e.g., "Prague, Czech Republic" or "New York, USA")
    USER_LOCATION: str = os.getenv("USER_LOCATION", "")

    # Cost tracking
    COST_CURRENCY: str = os.getenv("COST_CURRENCY", "CZK").upper()  # Default to CZK
    COST_HISTORY_MAX_MONTHS: int = int(
        os.getenv("COST_HISTORY_MAX_MONTHS", "120")
    )  # Max 10 years of history (120 months)

    # Gemini 3 pricing (per million tokens) - as of Dec 2025
    # These should be updated when Google changes pricing
    MODEL_PRICING = {
        "gemini-3-flash-preview": {
            "input": 0.075,  # $0.075 per million input tokens
            "output": 0.30,  # $0.30 per million output tokens
        },
        "gemini-3-pro-preview": {
            "input": 1.25,  # $1.25 per million input tokens
            "output": 5.00,  # $5.00 per million output tokens
        },
        "gemini-3-pro-image-preview": {
            "input": 2.00,  # $2.00 per million input tokens (text prompts)
            "output": 12.00,  # $12.00 per million output tokens (images + thinking)
        },
        "gemini-2.0-flash": {
            "input": 0.075,  # Used for title generation
            "output": 0.30,
        },
    }

    # Currency conversion rates (USD to other currencies)
    # These are fallback defaults - actual rates are loaded from database
    # Updated daily via scripts/update_currency_rates.py (systemd timer)
    CURRENCY_RATES = {
        "USD": 1.0,
        "CZK": 23.0,
        "EUR": 0.92,
        "GBP": 0.79,
    }

    @classmethod
    def is_development(cls) -> bool:
        """Check if running in development mode."""
        return cls.FLASK_ENV == "development"

    @classmethod
    def is_testing(cls) -> bool:
        """Check if running in testing mode."""
        return cls.FLASK_ENV == "testing"

    @classmethod
    def is_e2e_testing(cls) -> bool:
        """Check if running in E2E testing mode (browser tests with mocked backend).

        E2E tests set E2E_TESTING=true to enable auth bypass while still
        using FLASK_ENV=testing for other test-specific behavior.
        """
        return os.getenv("E2E_TESTING", "").lower() == "true"

    @classmethod
    def should_bypass_auth(cls) -> bool:
        """Check if auth should be bypassed.

        Auth is bypassed in:
        - Development mode (for local dev convenience)
        - E2E testing mode (browser tests need to skip real auth)

        NOT bypassed in:
        - Unit/integration tests (need to test auth behavior)
        - Production
        """
        return cls.is_development() or cls.is_e2e_testing()

    # Database
    DATABASE_PATH: Path = BASE_DIR / os.getenv("DATABASE_PATH", "chatbot.db")
    BLOB_STORAGE_PATH: Path = BASE_DIR / os.getenv("BLOB_STORAGE_PATH", "files.db")

    # File upload settings
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", str(20 * BYTES_PER_MB)))  # 20 MB default
    MAX_FILES_PER_MESSAGE: int = int(os.getenv("MAX_FILES_PER_MESSAGE", "10"))
    ALLOWED_FILE_TYPES: set[str] = set(
        os.getenv(
            "ALLOWED_FILE_TYPES",
            "image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain,text/markdown,application/json,text/csv",
        ).split(",")
    )

    # Image thumbnail settings
    THUMBNAIL_MAX_SIZE: tuple[int, int] = (
        int(os.getenv("THUMBNAIL_MAX_WIDTH", "400")),
        int(os.getenv("THUMBNAIL_MAX_HEIGHT", "400")),
    )
    THUMBNAIL_QUALITY: int = int(os.getenv("THUMBNAIL_QUALITY", "85"))  # JPEG quality (1-100)
    THUMBNAIL_SKIP_THRESHOLD_BYTES: int = int(
        os.getenv("THUMBNAIL_SKIP_THRESHOLD", str(100 * BYTES_PER_KB))
    )  # 100KB - skip thumbnail for small images
    THUMBNAIL_WORKER_THREADS: int = int(os.getenv("THUMBNAIL_WORKER_THREADS", "2"))
    THUMBNAIL_RESAMPLING: str = os.getenv(
        "THUMBNAIL_RESAMPLING", "BILINEAR"
    )  # BILINEAR (fast) or LANCZOS (quality)
    THUMBNAIL_STALE_THRESHOLD_SECONDS: int = int(
        os.getenv("THUMBNAIL_STALE_THRESHOLD", "60")
    )  # Recovery threshold for stuck pending thumbnails

    # Cost history settings
    COST_HISTORY_DEFAULT_LIMIT: int = int(
        os.getenv("COST_HISTORY_DEFAULT_LIMIT", "12")
    )  # Default to 12 months

    # Currency formatting (decimal places)
    CURRENCY_DECIMALS = {
        "USD": 4,
        "EUR": 4,
        "GBP": 4,
        "CZK": 2,
    }

    # Title generation settings
    TITLE_GENERATION_MODEL = "gemini-2.0-flash"
    TITLE_GENERATION_TEMPERATURE = 0.7
    TITLE_MAX_LENGTH = 60
    TITLE_TRUNCATE_LENGTH = 57  # Leaves room for "..."
    TITLE_CONTEXT_MAX_LENGTH = 500  # Max chars of context to send for title generation
    TITLE_FALLBACK_LENGTH = 50  # Length for fallback title from user message

    # LLM settings
    GEMINI_DEFAULT_TEMPERATURE = 1.0

    # Default values (must match frontend)
    DEFAULT_CONVERSATION_TITLE = "New Conversation"
    DEFAULT_IMAGE_GENERATION_MESSAGE = "I've generated the image for you."

    # Metadata marker for extracting sources/images from LLM response
    METADATA_MARKER = "<!-- METADATA:"

    # HTTP caching
    FILE_CACHE_MAX_AGE_SECONDS = 365 * SECONDS_PER_DAY  # 1 year

    # Web search settings
    WEB_SEARCH_DEFAULT_RESULTS = 5
    WEB_SEARCH_MAX_RESULTS = 10

    # HTML processing
    HTML_TEXT_MAX_LENGTH = 15000

    # Code execution sandbox settings
    CODE_SANDBOX_ENABLED: bool = os.getenv("CODE_SANDBOX_ENABLED", "true").lower() == "true"
    CODE_SANDBOX_TIMEOUT: int = int(os.getenv("CODE_SANDBOX_TIMEOUT", "30"))  # seconds
    CODE_SANDBOX_MEMORY_LIMIT: str = os.getenv("CODE_SANDBOX_MEMORY_LIMIT", "512m")
    CODE_SANDBOX_CPU_LIMIT: float = float(os.getenv("CODE_SANDBOX_CPU_LIMIT", "1.0"))
    # Docker image for sandbox (use public Docker Hub image to avoid auth issues)
    CODE_SANDBOX_IMAGE: str = os.getenv("CODE_SANDBOX_IMAGE", "python:3.11-slim-trixie")
    # Pre-installed libraries in the sandbox (cached in container image)
    CODE_SANDBOX_LIBRARIES: list[str] = [
        lib.strip()
        for lib in os.getenv(
            "CODE_SANDBOX_LIBRARIES",
            "numpy,pandas,matplotlib,scipy,sympy,pillow,reportlab,fpdf2",
        ).split(",")
        if lib.strip()
    ]

    # Logging truncation settings
    QUERY_LOG_MAX_LENGTH = 200
    PARAMS_LOG_MAX_LENGTH = 100
    PAYLOAD_LOG_MAX_LENGTH = 500
    FILE_DATA_SNIPPET_LENGTH = 100

    # User memory settings
    USER_MEMORY_LIMIT: int = int(os.getenv("USER_MEMORY_LIMIT", "100"))  # Max memories per user
    USER_MEMORY_WARNING_THRESHOLD: int = int(
        os.getenv("USER_MEMORY_WARNING_THRESHOLD", "80")
    )  # Warn LLM to consolidate at this count

    # Pagination settings
    # Client requests appropriate size based on viewport; these are server-side limits
    CONVERSATIONS_DEFAULT_PAGE_SIZE: int = int(os.getenv("CONVERSATIONS_DEFAULT_PAGE_SIZE", "30"))
    CONVERSATIONS_MAX_PAGE_SIZE: int = int(os.getenv("CONVERSATIONS_MAX_PAGE_SIZE", "100"))
    MESSAGES_DEFAULT_PAGE_SIZE: int = int(os.getenv("MESSAGES_DEFAULT_PAGE_SIZE", "50"))
    MESSAGES_MAX_PAGE_SIZE: int = int(os.getenv("MESSAGES_MAX_PAGE_SIZE", "200"))

    @classmethod
    def validate(cls) -> list[str]:
        """Validate required configuration. Returns list of errors with clear guidance."""
        errors: list[str] = []

        # Always required
        if not cls.GEMINI_API_KEY:
            errors.append(
                "GEMINI_API_KEY is required. "
                "Get your API key from https://ai.google.dev/ and set it in .env"
            )

        # Production-only requirements
        if not cls.is_development():
            if not cls.GOOGLE_CLIENT_ID:
                errors.append(
                    "GOOGLE_CLIENT_ID is required in production. "
                    "Set up OAuth at https://console.cloud.google.com/apis/credentials "
                    "or set FLASK_ENV=development to skip authentication"
                )
            if not cls.ALLOWED_EMAILS:
                errors.append(
                    "ALLOWED_EMAILS is required in production. "
                    "Set a comma-separated list of allowed email addresses "
                    "or set FLASK_ENV=development to skip authentication"
                )
            if cls.JWT_SECRET_KEY == "dev-secret-change-me":
                errors.append(
                    "JWT_SECRET_KEY must be set to a secure random value in production. "
                    'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
                )
            elif len(cls.JWT_SECRET_KEY) < 32:
                errors.append(
                    f"JWT_SECRET_KEY must be at least 32 characters for security (got {len(cls.JWT_SECRET_KEY)}). "
                    'Generate a secure key with: python -c "import secrets; print(secrets.token_hex(32))"'
                )

        # Validate numeric ranges
        if cls.PORT < 1 or cls.PORT > 65535:
            errors.append(f"PORT must be between 1 and 65535, got {cls.PORT}")

        if cls.MAX_FILE_SIZE < 1:
            errors.append(f"MAX_FILE_SIZE must be positive, got {cls.MAX_FILE_SIZE}")

        if cls.MAX_FILES_PER_MESSAGE < 1:
            errors.append(
                f"MAX_FILES_PER_MESSAGE must be at least 1, got {cls.MAX_FILES_PER_MESSAGE}"
            )

        # Validate currency
        if cls.COST_CURRENCY not in cls.CURRENCY_RATES:
            valid_currencies = ", ".join(sorted(cls.CURRENCY_RATES.keys()))
            errors.append(
                f"COST_CURRENCY '{cls.COST_CURRENCY}' is not supported. "
                f"Valid currencies: {valid_currencies}"
            )

        # Validate log level
        valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if cls.LOG_LEVEL not in valid_log_levels:
            errors.append(
                f"LOG_LEVEL '{cls.LOG_LEVEL}' is not valid. "
                f"Valid levels: {', '.join(sorted(valid_log_levels))}"
            )

        return errors
