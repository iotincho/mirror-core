"""Legacy synchronous error translation; cursor identity lives in core."""

from src.core.extractors.personal_axes import pagination
from src.core.extractors.personal_axes.models import AxisError as CoreAxisError
from src.extractors.personal_axes.contracts import AxisError

encode = pagination.encode
decode = pagination.decode
next_cursor = pagination.next_cursor


def position(cursor, scope):
    try:
        return pagination.position(cursor, scope)
    except CoreAxisError as error:
        raise AxisError(error.code, 422) from None


def page(items, scope, cursor, limit, key):
    try:
        return pagination.page(items, scope, cursor, limit, key)
    except CoreAxisError as error:
        raise AxisError(error.code, 422) from None
