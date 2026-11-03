"""Upgrade/downgrade with legacy data in a newly created disposable database."""

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Column, MetaData, Table, Uuid, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from src.adapters.storage.postgres.base import Base
from src.adapters.storage.postgres.journals import PostgresJournals
from src.adapters.storage.postgres.models import ProcessingRecord
from src.core.journals.rules import activate
from src.core.journals.templates import PREPARATION_TEMPLATE

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("JOURNALS_TEST_DATABASE_URL"),
        reason="requires isolated journals PostgreSQL",
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_upgrade_keeps_legacy_accounts_sessions_and_preferences_and_downgrade_is_explicit():
    configured = make_url(os.environ["JOURNALS_TEST_DATABASE_URL"])
    assert configured.database.startswith("journals_test")
    database = "journals_test_migration_" + uuid4().hex
    admin = create_async_engine(
        configured.set(database="postgres"), isolation_level="AUTOCOMMIT", hide_parameters=True
    )
    engine = None
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{database}"'))
    try:
        target = configured.set(database=database)
        environment = {**os.environ, "DATABASE_URL": target.render_as_string(hide_password=False)}

        async def migrate(*arguments):
            # Explicitly disable dotenv loading; only the disposable URL is consumed.
            source = (
                "from src.bootstrap.settings import Settings; "
                "Settings.model_config['env_file'] = None; "
                "from alembic.config import main; main()"
            )
            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-c", source, *arguments],
                env=environment,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stderr

        await migrate("upgrade", "20261029_22")
        engine = create_async_engine(target, hide_parameters=True)
        owner = uuid4()
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    'INSERT INTO "user" '
                    "(id,email,hashed_password,is_active,is_superuser,is_verified) "
                    "VALUES (:owner,'legacy@example.com','unused',true,false,false)"
                ),
                {"owner": owner},
            )
            await connection.execute(
                text(
                    "INSERT INTO accesstoken(token,user_id,created_at,session_version) "
                    "VALUES ('legacy-synthetic-token',:owner,now(),0)"
                ),
                {"owner": owner},
            )
            await connection.execute(
                text(
                    "INSERT INTO invitation_preferences"
                    "(user_id,enabled,local_time,timezone,updated_at) "
                    "VALUES (:owner,false,'17:00','UTC',now())"
                ),
                {"owner": owner},
            )
        await migrate("upgrade", "20261103_23")
        from sqlalchemy.ext.asyncio import async_sessionmaker

        repository = PostgresJournals(async_sessionmaker(engine))
        await repository.install_template(PREPARATION_TEMPLATE)
        old_run = activate(
            PREPARATION_TEMPLATE, run_id=uuid4(), owner=owner, timezone="UTC", now=datetime.now(UTC)
        )
        async with repository.transaction(owner) as transaction:
            await transaction.save(old_run, expected_revision=None)
        async with engine.begin() as connection:
            # Actual v1 JSON predates optional catalogs, including immutable revisions.
            await connection.execute(
                text("UPDATE journal_templates SET definition=definition-'catalogs'")
            )
            await connection.execute(
                text("UPDATE journal_run_revisions SET snapshot=snapshot-'catalogs'")
            )
        await migrate("upgrade", "20261103_24")
        job, preparation = uuid4(), uuid4()
        async with engine.begin() as connection:
            await connection.execute(
                ProcessingRecord.__table__.insert().values(
                    id=job,
                    user_id=owner,
                    workflow="question_preparation",
                    workflow_version=1,
                    resource_kind="question_preparation",
                    resource_id=preparation,
                    stage="question_context",
                ),
            )
            await connection.execute(
                text(
                    "INSERT INTO question_preparations"
                    "(id,user_id,processing_id,due_at,preference_version,status,"
                    "configuration,created_at,expires_at) "
                    "VALUES (:preparation,:owner,:job,now(),now(),'pending','{}',"
                    "now(),now()+interval '1 day')"
                ),
                {"preparation": preparation, "owner": owner, "job": job},
            )
        await migrate("upgrade", "head")
        await migrate("upgrade", "head")

        def differences(connection):
            metadata = MetaData()
            Table("user", metadata, Column("id", Uuid(), primary_key=True))
            Table(
                "invitations",
                metadata,
                Column("id", Uuid(), primary_key=True),
                Column("user_id", Uuid()),
            )
            for table in Base.metadata.tables.values():
                if table.name.startswith("journal_"):
                    table.to_metadata(metadata)
            context = MigrationContext.configure(
                connection,
                opts={
                    "include_object": lambda obj, name, kind, reflected, other: (
                        name.startswith("journal_") if kind == "table" else True
                    ),
                },
            )
            return compare_metadata(context, metadata)

        async with engine.connect() as connection:
            assert not await connection.run_sync(differences)
            assert (
                await connection.scalar(text("SELECT context_key FROM question_preparations"))
                == "free"
            )
            assert await connection.scalar(text("SELECT count(*) FROM journal_runs")) == 1
            assert await connection.scalar(text("SELECT count(*) FROM journal_templates")) == 1
            assert await connection.scalar(text("SELECT count(*) FROM journal_entries")) == 0
            assert await connection.scalar(text("SELECT count(*) FROM accesstoken")) == 1
            assert (
                await connection.execute(
                    text("SELECT enabled,local_time,timezone FROM invitation_preferences")
                )
            ).one() == (False, "17:00", "UTC")
        async with repository.transaction(owner) as transaction:
            assert await transaction.run(old_run.id, 1) == old_run
        await repository.install_template(PREPARATION_TEMPLATE)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO question_preparations"
                    "(id,user_id,processing_id,due_at,preference_version,status,"
                    "configuration,created_at,expires_at,context_key) "
                    "SELECT :id,user_id,processing_id,due_at,preference_version,status,"
                    "configuration,created_at,expires_at,'journal:synthetic' "
                    "FROM question_preparations WHERE id=:previous"
                ),
                {"id": uuid4(), "previous": preparation},
            )
        await migrate("downgrade", "20261103_24")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM question_preparations")) == 1
            assert (
                await connection.scalar(text("SELECT id FROM question_preparations")) == preparation
            )
        await migrate("downgrade", "20261029_22")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT to_regclass('journal_templates')")) is None
            assert await connection.scalar(text('SELECT count(*) FROM "user"')) == 1
            assert await connection.scalar(text("SELECT count(*) FROM accesstoken")) == 1
        await migrate("upgrade", "head")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM journal_templates")) == 0
    finally:
        if engine is not None:
            await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
        await admin.dispose()
