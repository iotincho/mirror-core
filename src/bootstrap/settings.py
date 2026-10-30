"""Runtime configuration loaded from environment variables."""

from functools import lru_cache
from ipaddress import ip_network
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings shared by the API and future processing components."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    platform_activity_enabled: bool = Field(
        default=False, validation_alias="PLATFORM_ACTIVITY_ENABLED"
    )
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")
    sentry_dsn: str = Field(default="", validation_alias="SENTRY_DSN", repr=False)
    sentry_release: str = Field(default="", validation_alias="SENTRY_RELEASE")
    sentry_traces_sample_rate: float = Field(
        default=1.0, ge=0, le=1, validation_alias="SENTRY_TRACES_SAMPLE_RATE"
    )
    rabbitmq_url: str = Field(
        default="amqp://guest:guest@localhost:5672/",
        validation_alias="RABBITMQ_URL",
        repr=False,
    )
    processing_concurrency: int = Field(
        default=4,
        validation_alias="PROCESSING_CONCURRENCY",
        gt=0,
    )
    processing_queue_name: str = Field(
        default="el_espejo.processing.v1",
        validation_alias="PROCESSING_QUEUE_NAME",
        min_length=1,
    )
    processing_lease_seconds: int = Field(
        default=90,
        validation_alias="PROCESSING_LEASE_SECONDS",
        ge=15,
    )
    web_push_public_key: str | None = Field(default=None, validation_alias="WEB_PUSH_PUBLIC_KEY")
    web_push_private_key: str | None = Field(
        default=None,
        validation_alias="WEB_PUSH_PRIVATE_KEY",
        repr=False,
    )
    web_push_subject: str | None = Field(default=None, validation_alias="WEB_PUSH_SUBJECT")
    web_push_allowed_hosts: list[str] = Field(
        default=[
            "fcm.googleapis.com",
            "push.services.mozilla.com",
            "push.apple.com",
            "notify.windows.com",
        ],
        validation_alias="WEB_PUSH_ALLOWED_HOSTS",
    )
    web_push_allowed_origins: list[str] = Field(
        default=[],
        validation_alias="WEB_PUSH_ALLOWED_ORIGINS",
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    database_url: str = Field(
        default="postgresql+asyncpg://el_espejo:el-espejo-local-password@localhost:5432/el_espejo",
        validation_alias="DATABASE_URL",
        repr=False,
    )
    arcadedb_http_url: str = Field(
        default="http://localhost:2480",
        validation_alias="ARCADEDB_HTTP_URL",
    )
    arcadedb_database: str = Field(default="el_espejo", validation_alias="ARCADEDB_DATABASE")
    arcadedb_username: str = Field(default="root", validation_alias="ARCADEDB_USERNAME")
    arcadedb_password: str = Field(
        default="el-espejo-local-password",
        validation_alias="ARCADEDB_ROOT_PASSWORD",
        repr=False,
    )
    arcadedb_instance_key: str = Field(
        default="primary",
        validation_alias="ARCADEDB_INSTANCE_KEY",
    )
    documents_path: Path = Field(default=Path("data/documents"), validation_alias="DOCUMENTS_PATH")
    audio_notes_path: Path = Field(
        default=Path("data/audio-notes"), validation_alias="AUDIO_NOTES_PATH"
    )
    workspaces_path: Path = Field(
        default=Path("data/users"),
        validation_alias="WORKSPACES_PATH",
    )
    llm_provider: str = Field(default="openai", validation_alias="LLM_PROVIDER")
    daily_question_mode: Literal["curated", "personalized"] = Field(
        default="curated", validation_alias="DAILY_QUESTION_MODE"
    )
    daily_question_model: str | None = Field(default=None, validation_alias="DAILY_QUESTION_MODEL")
    daily_question_max_calls_per_day: int = Field(
        default=1000, ge=0, le=100000, validation_alias="DAILY_QUESTION_MAX_CALLS_PER_DAY"
    )
    daily_question_max_followups: int = Field(
        default=1, ge=1, le=14, validation_alias="DAILY_QUESTION_MAX_FOLLOWUPS"
    )
    daily_question_rest_days: int = Field(
        default=7, ge=1, le=90, validation_alias="DAILY_QUESTION_REST_DAYS"
    )
    daily_question_silence_hours: int = Field(
        default=48, ge=1, le=720, validation_alias="DAILY_QUESTION_SILENCE_HOURS"
    )
    daily_question_general_every: int = Field(
        default=4, ge=2, le=14, validation_alias="DAILY_QUESTION_GENERAL_EVERY"
    )
    daily_question_max_input_tokens: int = Field(
        default=24000, ge=8000, le=64000, validation_alias="DAILY_QUESTION_MAX_INPUT_TOKENS"
    )
    daily_question_max_output_tokens: int = Field(
        default=3000, ge=1000, le=8000, validation_alias="DAILY_QUESTION_MAX_OUTPUT_TOKENS"
    )
    daily_question_timeout_seconds: int = Field(
        default=45, ge=1, le=120, validation_alias="DAILY_QUESTION_TIMEOUT_SECONDS"
    )
    daily_question_concurrency: int = Field(
        default=2, ge=1, le=8, validation_alias="DAILY_QUESTION_CONCURRENCY"
    )
    daily_question_lead_minutes: int = Field(
        default=30, ge=1, le=120, validation_alias="DAILY_QUESTION_LEAD_MINUTES"
    )
    personal_axes_enabled: bool = Field(default=False, validation_alias="PERSONAL_AXES_ENABLED")
    personal_axes_preview_hours: int = Field(
        default=72, ge=1, le=720, validation_alias="PERSONAL_AXES_PREVIEW_HOURS"
    )
    personal_axes_max_input_chars: int = Field(
        default=100000, ge=1000, le=1000000, validation_alias="PERSONAL_AXES_MAX_INPUT_CHARS"
    )
    personal_axes_max_output_tokens: int = Field(
        default=6000, ge=256, le=32000, validation_alias="PERSONAL_AXES_MAX_OUTPUT_TOKENS"
    )
    personal_axes_preview_concurrency: int = Field(
        default=2, ge=1, le=5, validation_alias="PERSONAL_AXES_PREVIEW_CONCURRENCY"
    )
    personal_axes_max_pending_previews: int = Field(
        default=10, ge=1, le=100, validation_alias="PERSONAL_AXES_MAX_PENDING_PREVIEWS"
    )
    document_title_read_limit: int = Field(
        default=5, ge=0, le=100, validation_alias="DOCUMENT_TITLE_READ_LIMIT"
    )
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY", repr=False)
    openai_model: str | None = Field(default=None, validation_alias="OPENAI_MODEL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small", validation_alias="OPENAI_EMBEDDING_MODEL"
    )
    openai_embedding_dimensions: int = Field(
        default=1536, gt=0, le=1536, validation_alias="OPENAI_EMBEDDING_DIMENSIONS"
    )
    embedding_segmentation_threshold: int = Field(
        default=2000, gt=0, le=8192, validation_alias="EMBEDDING_SEGMENTATION_THRESHOLD"
    )
    embedding_section_max_tokens: int = Field(
        default=2000, ge=32, le=8192, validation_alias="EMBEDDING_SECTION_MAX_TOKENS"
    )
    embedding_section_target_tokens: int = Field(
        default=1000, ge=32, le=8192, validation_alias="EMBEDDING_SECTION_TARGET_TOKENS"
    )
    openai_transcription_model: str = Field(
        default="gpt-transcribe", validation_alias="OPENAI_TRANSCRIPTION_MODEL"
    )
    audio_max_upload_bytes: int = Field(
        default=25 * 1024 * 1024, validation_alias="AUDIO_MAX_UPLOAD_BYTES", gt=0
    )
    document_max_upload_bytes: int = Field(
        default=5 * 1024 * 1024,
        validation_alias="DOCUMENT_MAX_UPLOAD_BYTES",
        gt=0,
    )
    provider_timeout_seconds: float = Field(
        default=120, validation_alias="PROVIDER_TIMEOUT_SECONDS", gt=0
    )
    provider_max_concurrency: int = Field(
        default=4, validation_alias="PROVIDER_MAX_CONCURRENCY", gt=0
    )
    graph_timeout_seconds: float = Field(default=30, validation_alias="GRAPH_TIMEOUT_SECONDS", gt=0)
    graph_max_connections: int = Field(default=20, validation_alias="GRAPH_MAX_CONNECTIONS", gt=0)
    auth_session_secret: str | None = Field(
        default=None,
        validation_alias="AUTH_SESSION_SECRET",
        repr=False,
    )
    workspace_secret_key: str | None = Field(
        default=None,
        validation_alias="WORKSPACE_SECRET_KEY",
        repr=False,
    )
    google_oauth_client_id: str | None = Field(
        default=None,
        validation_alias="GOOGLE_OAUTH_CLIENT_ID",
        repr=False,
    )
    google_oauth_client_secret: str | None = Field(
        default=None,
        validation_alias="GOOGLE_OAUTH_CLIENT_SECRET",
        repr=False,
    )
    google_oauth_redirect_url: str | None = Field(
        default=None,
        validation_alias="GOOGLE_OAUTH_REDIRECT_URL",
    )
    google_oauth_state_secret: str | None = Field(
        default=None,
        validation_alias="GOOGLE_OAUTH_STATE_SECRET",
        repr=False,
    )
    auth_session_ttl_seconds: int = Field(
        default=604800,
        validation_alias="AUTH_SESSION_TTL_SECONDS",
        gt=0,
    )
    auth_cookie_secure: bool = Field(default=True, validation_alias="AUTH_COOKIE_SECURE")
    resend_api_key: str | None = Field(default=None, validation_alias="RESEND_API_KEY", repr=False)
    auth_email_from: str | None = Field(default=None, validation_alias="AUTH_EMAIL_FROM")
    password_recovery_secret: str | None = Field(
        default=None, validation_alias="PASSWORD_RECOVERY_SECRET", repr=False
    )
    password_recovery_trusted_proxy_cidrs: list[str] = Field(
        default_factory=list, validation_alias="PASSWORD_RECOVERY_TRUSTED_PROXY_CIDRS"
    )

    @field_validator("password_recovery_trusted_proxy_cidrs")
    @classmethod
    def validate_recovery_proxies(cls, values):
        for value in values:
            if ip_network(value).prefixlen == 0:
                raise ValueError("Recovery proxies must be explicit trusted networks")
        return values


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide immutable settings instance."""
    return Settings()
