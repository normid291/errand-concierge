"""Application configuration.

Everything is read from environment variables (optionally via a `.env` file)
so the same image can run locally, in Docker, and on a PaaS.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _origins() -> list[str]:
    raw = os.environ.get("ALLOWED_ORIGINS", "")
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


@dataclass(frozen=True)
class Settings:
    """Runtime settings resolved once at startup."""

    base_dir: Path = BASE_DIR
    database_path: Path = BASE_DIR / "data" / "errands.db"
    demo_mode: bool = False
    bedrock_api_key: str = ""
    bedrock_base_url: str = "https://bedrock-mantle.us-east-1.api.aws/v1"
    bedrock_model_id: str = "openai.gpt-oss-120b"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/integrations/google/callback"
    calendar_timezone: str = "Africa/Lagos"
    allowed_origins: list[str] = field(default_factory=list)
    app_secret: str = ""
    frontend_url: str = ""
    session_ttl_hours: int = 12
    max_sessions: int = 200
    max_message_chars: int = 4000

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def model_configured(self) -> bool:
        return bool(self.bedrock_api_key)

    @property
    def assistant_mode(self) -> str:
        """`demo` when no model credentials are present, `bedrock` otherwise."""
        return "demo" if self.demo_mode or not self.model_configured else "bedrock"

    @classmethod
    def load(cls) -> Settings:
        load_dotenv(BASE_DIR / ".env")

        database_path = Path(os.environ.get("DATABASE_PATH", str(BASE_DIR / "data" / "errands.db")))
        if not database_path.is_absolute():
            database_path = (BASE_DIR / database_path).resolve()

        redirect_uri = os.environ.get(
            "GOOGLE_REDIRECT_URI",
            "http://localhost:8000/api/integrations/google/callback",
        )

        return cls(
            database_path=database_path,
            demo_mode=_bool("DEMO_MODE", False),
            bedrock_api_key=os.environ.get("BEDROCK_API_KEY", "").strip(),
            bedrock_base_url=os.environ.get(
                "BEDROCK_BASE_URL", "https://bedrock-mantle.us-east-1.api.aws/v1"
            ).rstrip("/"),
            bedrock_model_id=os.environ.get("BEDROCK_MODEL_ID", "openai.gpt-oss-120b"),
            google_client_id=os.environ.get("GOOGLE_CLIENT_ID", "").strip(),
            google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", "").strip(),
            google_redirect_uri=redirect_uri.rstrip("/"),
            calendar_timezone=os.environ.get("CALENDAR_TIMEZONE", "Africa/Lagos"),
            allowed_origins=_origins(),
            app_secret=os.environ.get("APP_SECRET", "").strip() or secrets.token_urlsafe(32),
            frontend_url=os.environ.get("FRONTEND_URL", "").strip().rstrip("/"),
            session_ttl_hours=_int("SESSION_TTL_HOURS", 12),
            max_sessions=_int("MAX_SESSIONS", 200),
            max_message_chars=_int("MAX_MESSAGE_CHARS", 4000),
        )
