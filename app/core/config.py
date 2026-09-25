"""Application settings from environment variables (or .env in dev); production fails fast on bad config."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Self

from pydantic import BeforeValidator, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_csv(value):
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


# Dev convenience default; the settings validator refuses it in production.
DEV_ONLY_DEFAULT_SECRET = "dev-only-secret-change-me-min-32-characters-long"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(Path(__file__).resolve().parents[2] / ".env"),
        extra="ignore",
    )

    environment: str = "development"

    database_url: str = "postgresql+asyncpg://veritrack:veritrack@localhost:5432/veritrack"

    jwt_secret_key: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    bcrypt_rounds: int = Field(default=12, ge=12)

    lockout_threshold: int = 5
    lockout_duration_minutes: int = 15

    # strict: the SPA and API share an origin (Vercel rewrite / reverse proxy)
    # none:   the SPA calls the API cross-site (VITE_API_BASE_URL) — needs HTTPS
    cookie_samesite: str = Field(default="strict", pattern="^(strict|lax|none)$")
    # proxies in front of the API: 0 direct, 1 Render/nginx, 2 Vercel rewrite → Render
    trusted_proxy_hops: int = Field(default=1, ge=0, le=5)

    cors_origins: Annotated[list[str], NoDecode, BeforeValidator(_split_csv)] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    m365_client_id: str | None = None
    m365_client_secret: str | None = None
    m365_tenant_id: str = "common"
    m365_redirect_uri: str = "http://localhost:8000/api/v1/auth/m365/callback"

    seed_admin_email: str = "admin@veritrack.io"
    # No default: without SEED_ADMIN_PASSWORD or --password the CLI generates one and prints it once.
    seed_admin_password: str | None = None

    # local  — filesystem, development only
    # volume — filesystem on a persistent disk (allowed in production)
    # s3     — S3-compatible object storage (AWS S3, R2, MinIO)
    storage_backend: str = "local"
    local_storage_root: str = "./storage-data"
    s3_endpoint_url: str | None = None
    s3_bucket: str = "veritrack"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    max_file_size_mb: int = 25
    max_files_per_batch: int = 20
    employee_id_pattern: str = r"^[A-Za-z0-9][A-Za-z0-9\-_/]{2,31}$"

    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # How uploads/analyses are executed:
    #   background — in the API process, off the request (default; no Redis
    #                needed; OCR runs in worker threads so the API stays fast)
    #   celery     — on Celery workers via Redis (horizontal scale-out)
    #   inline     — inside the request (tests / scripted demos)
    processing_mode: str = "background"

    # Retention policy: GETS batches + reports older than this many days are
    # purgeable by Master Admin (POST /settings/purge-obsolete-data).
    retention_days: int = 365

    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    # slowapi storage; use redis://… when running more than one API replica
    rate_limit_storage_uri: str = "memory://"

    # auto/rapid = RapidOCR (PP-OCRv4 on onnxruntime); test = JSON fixture engine
    ocr_engine: str = "auto"
    # parallel OCR engines per process (each holds its own ONNX sessions)
    ocr_concurrency: int = 2
    low_confidence_threshold: float = 0.75
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"

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
        return self.max_file_size_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def m365_enabled(self) -> bool:
        return bool(self.m365_client_id and self.m365_client_secret)

    @property
    def cookie_secure(self) -> bool:
        # Secure cookies always in production (and whenever SameSite=None,
        # which browsers require); relaxed only for plain-HTTP local dev.
        return self.is_production or self.cookie_samesite == "none"

    @field_validator("database_url", mode="before")
    @classmethod
    def _asyncpg_url(cls, value):
        """Accept the URLs hosting providers hand out (postgres://…,
        postgresql://…?sslmode=require) and route them through asyncpg."""
        if not isinstance(value, str):
            return value
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                value = "postgresql+asyncpg://" + value[len(prefix):]
        return value.replace("sslmode=require", "ssl=require")

    @model_validator(mode="after")
    def validate_secrets(self) -> Self:
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
