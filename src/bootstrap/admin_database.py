from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bootstrap.administration_settings import get_admin_settings


@lru_cache
def get_admin_engine():
    return create_async_engine(
        get_admin_settings().database_url, pool_pre_ping=True, hide_parameters=True
    )


@lru_cache
def get_admin_sessions():
    return async_sessionmaker(get_admin_engine(), expire_on_commit=False)


async def admin_session():
    async with get_admin_sessions()() as session:
        async with session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            yield session


async def admin_write_session():
    """Only explicit administrative mutations opt into a writable transaction."""
    async with get_admin_sessions()() as session:
        async with session.begin():
            yield session


async def close_admin_database():
    if get_admin_engine.cache_info().currsize:
        await get_admin_engine().dispose()
    get_admin_sessions.cache_clear()
    get_admin_engine.cache_clear()
