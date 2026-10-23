"""Alembic environment for the user-management PostgreSQL schema."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.adapters.storage.postgres import (
    recovery_models,  # noqa: F401
    workspace_models,  # noqa: F401
)
from src.adapters.storage.postgres.accounts import Base
from src.administration import models as admin_models  # noqa: F401
from src.config import get_settings
from src.exteriorization import models as invitation_models  # noqa: F401
from src.extractors.personal_axes import history_models as axis_history_models  # noqa: F401
from src.extractors.personal_axes import models as axis_models  # noqa: F401
from src.maintenance import models as maintenance_models  # noqa: F401
from src.notifications import models as notification_models  # noqa: F401
from src.processing import models as processing_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
