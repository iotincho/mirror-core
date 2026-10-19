"""Minimal configuration: administration needs PostgreSQL, not workspace secrets."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AdministrationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        default="postgresql+asyncpg://el_espejo:el-espejo-local-password@localhost:5432/el_espejo",
        validation_alias="DATABASE_URL",
        repr=False,
    )
    workspaces_path: Path = Field(default=Path("data/users"), validation_alias="WORKSPACES_PATH")
    inventory_max_age_seconds: int = Field(
        default=300, ge=30, validation_alias="ADMIN_INVENTORY_MAX_AGE_SECONDS"
    )


@lru_cache
def get_admin_settings():
    return AdministrationSettings()
