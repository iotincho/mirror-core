"""Translate SQL failures before they cross the axis port."""

from functools import wraps

from sqlalchemy.exc import SQLAlchemyError

from src.core.extractors.personal_axes.models import AxisError


def axis_database_call(function):
    @wraps(function)
    async def call(*args, **kwargs):
        try:
            return await function(*args, **kwargs)
        except SQLAlchemyError:
            raise AxisError("axis_storage_unavailable") from None

    return call
