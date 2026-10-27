"""Translate SQL failures at adapter entrypoints without exposing sessions to cases."""

from functools import wraps

from src.adapters.storage.postgres.state import database_errors


def database_call(function):
    @wraps(function)
    async def call(*args, **kwargs):
        async with database_errors():
            return await function(*args, **kwargs)
    return call
