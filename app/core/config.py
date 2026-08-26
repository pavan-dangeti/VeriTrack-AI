"""Application configuration.

All secrets come from environment variables (or a local .env file for dev).
The app fails fast at startup if required settings are missing in production.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator, Field, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_csv(value):
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


# noqa: S105 below - dev convenience default; validator refuses it in production
DEV_ONLY_DEFAULT_SECRET = "dev-only-secret-change-me-min-32-characters-long"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(Path(__file__).resolve().parents[2] / ".env"),
        extra="ignore",
    )

    environment: str = "development"

    database_url: str = "postgresql+asyncpg://veritrack:veritrack@localhost:5432/veritrack"
    test_database_url: str = (
        "postgresql+asyncpg://veritrack:veritrack@localhost:5432/veritrack_test"
    )

    jwt_secret_key: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    bcrypt_rounds: int = Field(default=12, ge=12)  # spec: cost factor 12+

    lockout_threshold: int = 5
    lockout_window_minutes: int = 15
    lockout_duration_minutes: int = 15

    cors_origins: Annotated[list[str], NoDecode, BeforeValidator(_split_csv)] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    m365_client_id: str | None = None
    m365_client_secret: str | None = None
    m365_tenant_id: str = "common"
    m365_redirect_uri: str = "http://localhost:8000/api/v1/auth/m365/callback"

    seed_admin_email: str = "admin@veritrack.io"
    seed_admin_password: str = "Bootstrap!Pass123"  # noqa: S105 - local bootstrap default; override via env

    # ---- Storage (Prompt #2) ----
    # local | s3 (S3-compatible: AWS S3, MinIO; Azure Blob adapter slots in
    # behind the same StorageBackend protocol)
    storage_backend: str = "local"
    local_storage_root: str = "./storage-data"
    s3_endpoint_url: str | None = None
    s3_bucket: str = "veritrack"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    # ---- Uploads ----
    max_file_size_mb: int = 25
    max_files_per_batch: int = 20
    employee_id_pattern: str = r"^[A-Za-z0-9][A-Za-z0-9\-_/]{2,31}$"

    # ---- Queue / workers ----
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_task_always_eager: bool = False  # true => process inline (tests/demo)

    # ---- Extraction / AI ----
    # auto = use RapidOCR when installed (recommended); see Dockerfile.ocr for
    # the full-Paddle production sidecar.
    ocr_engine: str = "auto"  # auto | rapid | paddle | test
    low_confidence_threshold: float = 0.75
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"

    # ---- Outbound email (Microsoft Graph) ----
    # dry_run => record what WOULD be sent, never hit the network.
    outbound_email_mode: str = "dry_run"
    graph_tenant_id: str | None = None
    graph_client_id: str | None = None
    graph_client_secret: str | None = None
    graph_sender_mailbox: str | None = None

    @property
    def graph_enabled(self) -> bool:
        return all(
            [self.graph_tenant_id, self.graph_client_id, self.graph_client_secret]
        )

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024  # noqa: S105 - local bootstrap only; rotate via env in real deploys

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def m365_enabled(self) -> bool:
        return bool(self.m365_client_id and self.m365_client_secret)

    @property
    def cookie_secure(self) -> bool:
        # Secure cookies always in production; relaxed only for plain-HTTP local dev.
        return self.is_production

    @model_validator(mode="after")
    def validate_secrets(self) -> Settings:
        if self.is_production:
            if not self.jwt_secret_key or len(self.jwt_secret_key) < 32:
                raise ValueError(
                    "JWT_SECRET_KEY must be set (>= 32 chars) when ENVIRONMENT=production"
                )
            if self.jwt_secret_key == DEV_ONLY_DEFAULT_SECRET:
                raise ValueError("JWT_SECRET_KEY is still the development default")
            wildcard = {o for o in self.cors_origins if "*" in o}
            if wildcard:
                raise ValueError("CORS_ORIGINS must not contain wildcards in production")
        if not self.jwt_secret_key:
            if self.environment != "development":
                raise ValueError("JWT_SECRET_KEY is required outside development")
            self.jwt_secret_key = DEV_ONLY_DEFAULT_SECRET
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
