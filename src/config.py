"""Runtime configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings shared by the API and future processing components."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = Field(default="development", validation_alias="ENVIRONMENT")
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
    extractions_path: Path = Field(
        default=Path("data/extractions"), validation_alias="EXTRACTIONS_PATH"
    )
    reflections_path: Path = Field(
        default=Path("data/reflections"), validation_alias="REFLECTIONS_PATH"
    )
    llm_provider: str = Field(default="openai", validation_alias="LLM_PROVIDER")
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY", repr=False)
    openai_model: str | None = Field(default=None, validation_alias="OPENAI_MODEL")
    openai_transcription_model: str = Field(
        default="gpt-transcribe", validation_alias="OPENAI_TRANSCRIPTION_MODEL"
    )
    audio_max_upload_bytes: int = Field(
        default=25 * 1024 * 1024, validation_alias="AUDIO_MAX_UPLOAD_BYTES", gt=0
    )
    reflection_provider: str = Field(default="openai", validation_alias="REFLECTION_PROVIDER")
    openai_reflection_model: str | None = Field(
        default=None, validation_alias="OPENAI_REFLECTION_MODEL"
    )
    embedding_provider: str = Field(default="openai", validation_alias="EMBEDDING_PROVIDER")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias="OPENAI_EMBEDDING_MODEL",
    )
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
    auth_session_ttl_seconds: int = Field(
        default=604800,
        validation_alias="AUTH_SESSION_TTL_SECONDS",
        gt=0,
    )
    auth_cookie_secure: bool = Field(default=True, validation_alias="AUTH_COOKIE_SECURE")

    openai_embedding_dimensions: int = Field(
        default=1536,
        validation_alias="OPENAI_EMBEDDING_DIMENSIONS",
        gt=0,
    )


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide immutable settings instance."""
    return Settings()
