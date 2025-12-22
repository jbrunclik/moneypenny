import os
from pathlib import Path

from dotenv import load_dotenv

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

    # Google Identity Services (GIS) - only Client ID needed
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")

    # JWT Authentication
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRATION_HOURS = 24 * 7  # 1 week

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

    @classmethod
    def is_development(cls) -> bool:
        """Check if running in development mode."""
        return cls.FLASK_ENV == "development"

    # Database
    DATABASE_PATH: Path = BASE_DIR / os.getenv("DATABASE_PATH", "chatbot.db")

    # File upload settings
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", str(20 * 1024 * 1024)))  # 20 MB default
    MAX_FILES_PER_MESSAGE: int = int(os.getenv("MAX_FILES_PER_MESSAGE", "10"))
    ALLOWED_FILE_TYPES: set[str] = set(
        os.getenv(
            "ALLOWED_FILE_TYPES",
            "image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain,text/markdown,application/json,text/csv",
        ).split(",")
    )

    # Tool result settings
    MAX_TOOL_RESULT_LENGTH: int = int(os.getenv("MAX_TOOL_RESULT_LENGTH", "2000"))  # Max chars for tool results

    @classmethod
    def validate(cls) -> list[str]:
        """Validate required configuration. Returns list of errors."""
        errors: list[str] = []

        if not cls.GEMINI_API_KEY:
            errors.append("GEMINI_API_KEY is required")

        if not cls.is_development():
            if not cls.GOOGLE_CLIENT_ID:
                errors.append("GOOGLE_CLIENT_ID is required (or set FLASK_ENV=development)")
            if not cls.ALLOWED_EMAILS:
                errors.append("ALLOWED_EMAILS is required (or set FLASK_ENV=development)")
            if cls.JWT_SECRET_KEY == "dev-secret-change-me":
                errors.append("JWT_SECRET_KEY must be set to a secure value in production")

        return errors
