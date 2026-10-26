"""Legacy HTTP error compatibility; canonical models/rules live in core."""

from functools import wraps

from src.adapters.access.api.public.personal_axes.errors import axis_status
from src.core.extractors.personal_axes.models import AxisError as CoreAxisError


class AxisError(CoreAxisError):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.status = status


def legacy_errors(function):
    @wraps(function)
    async def call(*args, **kwargs):
        try:
            return await function(*args, **kwargs)
        except AxisError:
            raise
        except CoreAxisError as error:
            raise AxisError(error.code, axis_status(error.code)) from None

    return call
