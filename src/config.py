"""Runtime configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings shared by the API and future processing components."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = Field(default="development", validation_alias="ENVIRONMENT")
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


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide immutable settings instance."""
    return Settings()
