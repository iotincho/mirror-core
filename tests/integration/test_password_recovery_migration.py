"""Upgrade legacy accounts in a disposable database, independent of the app DB."""

import os
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("RECOVERY_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL"
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_existing_local_and_google_accounts_are_classified_and_old_sessions_survive():
    configured = make_url(os.environ["RECOVERY_TEST_DATABASE_URL"])
    assert configured.database.startswith("recovery_test")
    database = "recovery_test_migration_" + uuid4().hex
    admin = create_async_engine(configured.set(database="postgres"), isolation_level="AUTOCOMMIT")
    engine = None
    async with admin.connect() as sql:
        await sql.execute(text(f'CREATE DATABASE "{database}"'))
    try:
        target = configured.set(database=database).render_as_string(hide_password=False)
        environment = {**os.environ, "DATABASE_URL": target}

        def migrate(*args):
            run = subprocess.run(
                [sys.executable, "-m", "alembic", *args],
                env=environment,
                capture_output=True,
                text=True,
            )
            assert run.returncode == 0, run.stderr

        migrate("upgrade", "20261013_09")
        engine = create_async_engine(target)
        local_id, google_id = uuid4(), uuid4()
        async with engine.begin() as sql:
            for user_id, email in [
                (local_id, "local@example.com"),
                (google_id, "google@example.com"),
            ]:
                await sql.execute(
                    text(
                        'INSERT INTO "user" '
                        "(id,email,hashed_password,is_active,is_superuser,is_verified) "
                        "VALUES (:id,:email,'unused',true,false,false)"
                    ),
                    {"id": user_id, "email": email},
                )
            await sql.execute(
                text(
                    "INSERT INTO oauth_account "
                    "(id,user_id,oauth_name,access_token,account_id,account_email) "
                    "VALUES (:id,:user,'google','unused','google-id','google@example.com')"
                ),
                {"id": uuid4(), "user": google_id},
            )
            await sql.execute(
                text(
                    "INSERT INTO accesstoken (token,user_id,created_at) "
                    "VALUES ('legacy-token',:user,now())"
                ),
                {"user": local_id},
            )
        migrate("upgrade", "head")
        migrate("upgrade", "head")
        async with engine.connect() as sql:
            rows = (
                await sql.execute(
                    text('SELECT id,password_login_enabled,session_version FROM "user"')
                )
            ).all()
            assert {row.id: row.password_login_enabled for row in rows} == {
                local_id: True,
                google_id: False,
            }
            assert all(row.session_version == 0 for row in rows)
            assert (
                await sql.scalar(
                    text("SELECT session_version FROM accesstoken WHERE token='legacy-token'")
                )
                == 0
            )
            assert (
                await sql.scalar(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_name='user' AND column_name='password_login_enabled'"
                    )
                )
                == "NO"
            )
        migrate("downgrade", "20261013_09")
        migrate("upgrade", "head")
    finally:
        if engine:
            await engine.dispose()
        async with admin.connect() as sql:
            await sql.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
        await admin.dispose()
